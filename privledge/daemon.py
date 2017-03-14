""" A daemon thread manager that can be controlled from the privledge shell
"""

from privledge import block
from privledge import settings
from privledge import utils
from privledge import messaging
from privledge.ledger import Ledger

import json
import socket

ledger = None
peers = dict()
_privkey = None
_udp_thread = None
_udp_hb_thread = None
_tcp_thread = None


# Create a ledger with a new public and private key
def create_ledger(pubkey, privkey):
    global ledger, _privkey

    # Create root block
    pubkey_hash = utils.gen_hash(pubkey)
    root_block = block.Block(block.BlockType.root, None, pubkey, pubkey_hash)
    root_block.sign(privkey, pubkey_hash)

    ledger = Ledger()
    ledger.append(root_block)
    _privkey = privkey

    # Start Listeners
    ledger_listeners(True)


def ledger_listeners(start):
    global _udp_thread, _udp_hb_thread, _tcp_thread

    if start:
        # Spawn UDP Persistent Listener thread
        _udp_thread = messaging.UDPListener(settings.BIND_IP, settings.BIND_PORT)
        _udp_thread.start()

        # Spawn UDP Heartbeat thread
        _udp_hb_thread = messaging.UDPHeartbeat()
        _udp_hb_thread.start()

        # Spawn TCP Listener thread
        _tcp_thread = messaging.TCPListener(settings.BIND_IP, settings.BIND_PORT)
        _tcp_thread.start()

    else:
        # Kill udp listener thread
        _udp_thread.stop.set()
        _udp_thread.join()
        _udp_thread = None

        # Kill udp hb thread
        _udp_hb_thread.stop.set()
        _udp_hb_thread.join()
        _udp_hb_thread = None


        # Kill tcp listener thread
        _tcp_thread.stop.set()
        _tcp_thread.join()
        _tcp_thread = None


# Join a ledger with a specified public key
def join_ledger(public_key_hash, member):
    global ledger

    # Check to make sure we aren't part of a ledger yet
    if ledger is not None:
        print("You are already a member of a ledger")
        return

    utils.log_message("Spawning TCP Connection Thread to {0}".format(member))
    join_message = messaging.Message(settings.MSG_TYPE_JOIN, public_key_hash).prep_tcp()
    thread = messaging.TCPMessageThread(member, join_message)
    thread.start()
    thread.join()

    # If the message is a success, import the key
    try:

        message = json.loads(thread.message, object_hook=utils.message_decoder)

        if message.message_type == settings.MSG_TYPE_SUCCESS:
            key = utils.get_key(message.message)
            key_hash = utils.gen_hash(key.publickey().exportKey())

            if public_key_hash == key_hash:
                # Hooray! We have a match
                utils.log_message("Joined ledger {}".format(public_key_hash), force=True)

                ## Sync Ledger
                messaging.ledger_sync(member)

                ## Request peers
                messaging.peer_sync(member)

                # Start Listeners
                ledger_listeners(True)

            else:
                raise ValueError('Public key returned does not match requested hash: {0}'.format(key_hash))

        else:
            raise ValueError('Response was not as expected: {0}'.format(message.message_type))

    except (ValueError, TypeError) as e:
        utils.log_message("Not a valid response from {0}: {1}".format(member, e))



def leave_ledger():
    global ledger, _udp_thread, _tcp_thread

    if ledger is not None:
        message = "Left ledger {0}".format(ledger.id)
        ledger = None

        # Kill the listners
        ledger_listeners(False)

    else:
        message = "Not a member of a ledger, cannot leave"

    return message

def discover_ledgers(ip='<broadcast>', port=settings.BIND_PORT, timeout = settings.DISCOVERY_TIMEOUT):
    print("Searching for available ledgers for {0} seconds...".format(timeout))
    utils.log_message("Starting Ledger Discovery")

    results = dict()

    # Send out discovery query
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    message = messaging.Message(settings.MSG_TYPE_DISCOVER).__repr__()
    s.sendto(message.encode(), (ip, port))
    try:
        # Listen for responses for 10 seconds
        s.settimeout(timeout)
        while True:
            data, address = s.recvfrom(4096)

            try:
                message = json.loads(data.decode(), object_hook=utils.message_decoder)

                if message.message_type == settings.MSG_TYPE_SUCCESS:
                    utils.log_message("Discovered ledger {0} at {1}".format(message.message, address))

                    # Received response
                    # Is the hash already in our list?
                    if message.message not in results:
                        # If hash isn't in the list, create a new set and add address to it
                        results[message.message] = set()
                    # Since there's already a set for our hash, we add to it
                    results[message.message].add(address)

            except:
                utils.log_message("Malformed response from {0}: {1}".format(data, address))

    except OSError as e:
        utils.log_message("Exception: {0}".format(e))
    finally:
        s.close()

    return results