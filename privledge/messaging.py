from socket import *
from privledge import utils
from privledge import settings
from privledge import daemon
from privledge import block
from privledge import ledger

import threading
import json
from datetime import datetime, timedelta
import time



lock = threading.Lock()


## Message Class ##
class Message():

    def __init__(self, type, message=None):
        self.type = type
        self.message = message

    def __repr__(self):
        return json.dumps(self, cls=utils.ComplexEncoder)

    def prep_tcp(self):
        return utils.append_len(self.__repr__())

    def reprJSON(self):
        return self.__dict__

def message_decoder(obj):
    #if len(obj) == 1 and '
    if 'type' in obj and 'message' in obj:
        return Message(obj['type'], obj['message'])
    elif 'signature' in obj and 'pubkey' in obj:
        return block.Block(obj['type'], obj['predecessor'], obj['pubkey'], obj['pubkey_hash'], obj['signature'], obj['signatory_hash'])
    return obj


def ledger_sync(target, block_hash=None):
    utils.log_message("Requesting ledger from {0}".format(target))

    ledger_message = Message(settings.MSG_TYPE_LEDGER, block_hash).prep_tcp()
    thread = TCPMessageThread(target, ledger_message)
    thread.start()
    thread.join()

    message = json.loads(thread.message, object_hook=message_decoder)

    # Add received blocks to our ledger
    if daemon.ledger is None:
        daemon.ledger = ledger.Ledger()

    for block in message.message:
        daemon.ledger.append(block)


def peer_sync(target):
    utils.log_message("Requesting peers from {0}".format(target))

    ledger_message = Message(settings.MSG_TYPE_PEER, None).prep_tcp()
    thread = TCPMessageThread(target, ledger_message)
    thread.start()
    thread.join()

    message = json.loads(thread.message, object_hook=message_decoder)

    #for peer in message:
    #    daemon.peers.

    #peers[member] = datetime.now()



### TCP Thread Classes ###

# Persistent TCP Listener thread that listens for messages
class TCPListener(threading.Thread):

    def __init__(self, ip=settings.BIND_IP, port=settings.BIND_PORT):
        super(TCPListener, self).__init__()
        with lock:
            utils.log_message("Starting TCP Listener Thread")
        self.daemon = True
        self._port = port
        self._ip = ip
        self.stop = threading.Event()
        self.stop.clear()

        self.tcp_server_socket = socket(AF_INET, SOCK_STREAM)

    def run(self):
        # Listen for ledger client connection requests
        with lock:
            utils.log_message("Listening for ledger messages on port {0}".format(self._port))

        try:
            self.tcp_server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            self.tcp_server_socket.setblocking(False)
            self.tcp_server_socket.bind((self._ip, self._port))
            self.tcp_server_socket.listen(5)

            # List for managing spawned threads
            socket_threads = []

            # Non-blocking socket loop that can be interrupted with a signal/event
            while True and not self.stop.is_set():
                try:
                    client_socket, address = self.tcp_server_socket.accept()

                    # Spawn thread
                    client_thread = TCPConnectionThread(client_socket)
                    client_thread.start()
                    socket_threads.append(client_thread)

                except Exception as e:
                    continue

            # Clean up all the threads
            for thread in socket_threads:
                thread.join()

        except Exception as e:
            print("Could not bind to port: {0}".format(e))
        finally:
            self.tcp_server_socket.close()

# Generic outbound TCP connection handler
class TCPMessageThread(threading.Thread):

    def __init__(self, target, message, timeout=5):
        super(TCPMessageThread, self).__init__()
        with lock:
            utils.log_message("Sending Message to {0} {1}: {2}{3}".format(target[0], target[1], message[:10], '...'))
        self._target = target

        self.message = message
        self._timeout = timeout

    def run(self):
        tcp_message_socket = socket(AF_INET, SOCK_STREAM)
        tcp_message_socket.settimeout(self._timeout)

        try:
            tcp_message_socket.connect(self._target)
            tcp_message_socket.sendall(self.message.encode())

            # Get response
            self.message = ''
            message_size = None

            while True:
                if message_size is None:
                    data = tcp_message_socket.recv(settings.MSG_SIZE_BYTES)
                    # Convert first message size to an integer
                    message_size = int(data.decode())
                elif len(self.message) < message_size:
                    data = tcp_message_socket.recv(4096)
                    self.message += data.decode()
                else:
                    break

        except ValueError as e:
            with lock:
                utils.log_message('Received invalid response from {0}'.format(tcp_message_socket.getsockname()))

        except Exception as e:
            with lock:
                utils.log_message('Could not send or receive message to or from the ledger at {0}:\n{1}\n{2}'.format(tcp_message_socket.getsockname()[0], self.message, e), force=True)

        else:
            with lock:
                utils.log_message(
                    "Received Response from {0} {1}: {2}{3}".format(self._target[0], self._target[1], self.message[:10],'...'))

        finally:
            tcp_message_socket.close()

# Generic inbound TCP connection handler
class TCPConnectionThread(threading.Thread):

    def __init__(self, socket):
        super(TCPConnectionThread, self).__init__()
        with lock:
            utils.log_message("Spawning TCP Connection Thread from {0}".format(socket.getsockname()))
        self._socket = socket

    def run(self):

        # Get message
        message = ''
        message_size = None
        try:
            while True:
                if message_size is None:
                    data = self._socket.recv(settings.MSG_SIZE_BYTES)
                    # Convert first message size to an integer
                    message_size = int(data.decode())
                elif len(message) < message_size:
                    data = self._socket.recv(4096)
                    message += data.decode()
                else:
                    break
        except ValueError as e:
            utils.log_message('Received invalid packet from {0}'.format(self._socket.getsockname()))
            return

        with lock:
            utils.log_message("Received message from {0}:\n{1}".format(self._socket.getsockname(), message))

        message = json.loads(message, object_hook=message_decoder)


        ## JOIN LEDGER ##
        if message.type == settings.MSG_TYPE_JOIN:
            if message.message == daemon.ledger.id:
                # Respond with success and the root key
                response = Message(settings.MSG_TYPE_SUCCESS, daemon.ledger.root.pubkey).prep_tcp()
                self._respond(response)
                return
            else:
                self._respond_error()
                return
        elif message.type == settings.MSG_TYPE_PEER:
            # Respond with list of peers
            peer_list = list(daemon.peers.keys())
            response = Message(settings.MSG_TYPE_SUCCESS, peer_list).prep_tcp()
            self._respond(response)
            return

        elif message.type == settings.MSG_TYPE_LEDGER:
            # Respond with the ledger
            ledger_list = daemon.ledger.to_list(message.message)

            if ledger_list is None:
                self._respond_error()
                return

            response = Message(settings.MSG_TYPE_SUCCESS, ledger_list).prep_tcp()
            self._respond(response)
            return

        # No response, send error status
        else:
            self._respond_error()
            return

    def _respond_error(self):
        response = Message(settings.MSG_TYPE_FAILURE).prep_tcp()
        self._respond(response)

    def _respond(self, message):
        with lock:
            utils.log_message(
                "Responded with message to {0}:\n{1}".format(self._socket.getsockname(), message))
        self._socket.sendall(message.encode())
        self._socket.shutdown(SHUT_WR)
        self._socket.recv(4096)
        self._socket.close()




### UDP Threading Classes ###

# Persistent UDP Listener thread that listens for discovery and heartbeat messages
class UDPListener(threading.Thread):

    def __init__(self, ip, port):
        super(UDPListener, self).__init__()
        with lock:
            utils.log_message("Starting UDP Listener Thread")
        self.daemon = True
        self._port = port
        self._ip = ip
        self.stop = threading.Event()

    def run(self):
        # Listen for ledger client connection requests
        with lock:
            utils.log_message("Listening for ledger discovery queries on port {0}".format(self._port))

        discovery_socket = socket(AF_INET, SOCK_DGRAM)
        discovery_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        discovery_socket.bind((self._ip, self._port))
        discovery_socket.setblocking(False)

        # Non-blocking socket loop that can be interrupted with a signal/event
        while True and not self.stop.is_set():
            try:
                data, addr = discovery_socket.recvfrom(1024)
            except OSError as e:
                continue
            else:
                message = json.loads(data.decode(), object_hook=message_decoder)
                # Decode Message Type
                if message.type == settings.MSG_TYPE_DISCOVER:
                    # Discovery Message
                    with lock:
                        utils.log_message("Received discovery inquiry from {0}, responding...".format(addr))
                    response = Message(settings.MSG_TYPE_SUCCESS, daemon.ledger.id).__repr__()
                    discovery_socket.sendto(response.encode(), addr)

                elif message.type == settings.MSG_TYPE_HB:
                    # Heartbeat Message
                    with lock :
                        utils.log_message("Received heartbeat from {0}".format(addr))
                    daemon.peers[addr] = datetime.now()

        discovery_socket.close()


# Persistent UDP Heartbeat Thread; sends hb to peers
class UDPHeartbeat(threading.Thread):

    def __init__(self):
        super(UDPHeartbeat, self).__init__()
        with lock:
            utils.log_message("Starting UDP Heartbeat Thread")
        self.daemon = True
        self.stop = threading.Event()

    def run(self):


        # Loop through the list of peers and send heartbeat messages
        while True and not self.stop.is_set():

            for target,last_beat in daemon.peers.items():

                if (last_beat + timedelta(milliseconds=settings.MSG_HB_TTL)) < datetime.now():
                    # Check for dead peers
                    with lock:
                        utils.log_message("Removing dead peer {0}".format(target))

                    del daemon.peers[target]
                else:
                    # Send heartbeat with root id to peers
                    s = socket(AF_INET, SOCK_DGRAM)
                    message = Message(settings.MSG_TYPE_HB, daemon.ledger.id).__repr__()

                    s.sendto(message, target)
                    utils.log_message("Heartbeat sent to {0}".format(target))
                    s.close()

            # Sleep the required time between heartbeats
            time.sleep(settings.MSG_HB_FREQ)