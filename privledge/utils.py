from xtermcolor import colorize
from enum import Enum
from privledge import settings
from privledge import messaging
from privledge import block
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA256

import random
import os.path
import base58
import json
from os import chmod

_hashes_fg = dict()
_hashes_bg = dict()


class Level(Enum):
    LOW = 3         # Used for repeating messages (eg heartbeat)
    MEDIUM = 2      # Use this level for low priority logs (messaging, etc)
    HIGH = 1        # Use this level for typical debug logging such as errors, spawning threads, and state change
    FORCE = 0       # Use this level to force printing - useful for errors affecting ledger state


def log_message(message, debug=Level.HIGH):
    """Log a message - use this function to do any printing to the console. From lowest priority:
    LOW: Use for repeating messages (eg heartbeat)
    MEDIUM: Use for low priority (eg messaging)
    HIGH (default): Use for typical debug logging such as errors, state change, thread spawning, etc
    FORCE: Force printing. Use to print to console regardless of debug state or for errors affecting ledger state"""

    if settings.debug >= debug.value:
        # Uses termcolor: https://pypi.python.org/pypi/termcolor
        color = 0x0000FF
        background = 0xCCCCCC

        if debug == Level.MEDIUM:
            color = 0x00FF00
        elif debug == Level.HIGH:
            color = 0xFFFF00
        elif debug == Level.FORCE:
            color = 0x0000FF

        print(colorize(message, rgb=color, bg=background))


def get_key(key=None):

    # Check for RSA key
    if key is not None:
        # Assume key is encoded
        try:
            return RSA.importKey(decode(key.strip()))
        except ValueError:

            # Try importing in a standard format (PEM bytestring)
            try:
                return RSA.importKey(key.strip())
            except ValueError:
                # Let's try to parse the message as a path
                if os.path.isfile(key):
                    log_message("{0} is a valid path.".format(key), Level.MEDIUM)
                    # Read given file
                    with open(key) as message_file:
                        message_contents = message_file.read()

                    try:
                        return RSA.importKey(message_contents.strip())
                    except Exception as err:
                        log_message("Provided key path is not valid")
                else:
                    log_message("Provided argument is not a key or key path")

    # Key is None
    return None


def gen_privkey(save=False, filename='id_rsa', location='', keylength=2048):
    log_message("Generating {0}-bit RSA key".format(keylength))

    key = RSA.generate(keylength)

    if save:
        with open("{0}{1}".format(location, filename), 'w') as content_file:
            chmod("{0}{1}".format(location, filename), 0o0600)
            content_file.write(key.exportKey())
        with open("{0}{1}.pub".format(location, filename), 'w') as content_file:
            content_file.write(key.publickey().exportKey())

    return key


def encode(bytestring):
    return base58.b58encode(bytestring)


def decode(string):
    return base58.b58decode(string)


def encode_key(key, public=True):
    if public:
        return encode(key.publickey().exportKey('DER'))
    else:
        return encode(key.exportKey('DER'))


def gen_hash(message):
    if isinstance(message, str):
        h = SHA256.new(message.encode('utf-8'))
    else:
        h = SHA256.new(message)

    return h.hexdigest()


def append_len(message):
    return str(len(message)).zfill(settings.MSG_SIZE_BYTES) + message


def message_decoder(obj):
    if 'msg_type' in obj and 'msg' in obj:
        return messaging.Message(obj['msg_type'], obj['msg'])
    elif 'blocktype' in obj and 'signature' in obj:
        return block.Block(block.BlockType[obj['blocktype']], obj['predecessor'], obj['message'], obj['signature'], obj['signatory_hash'])
    return obj


class ComplexEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):          # Handle bytes
            return obj.decode('ascii')
        if hasattr(obj, 'repr_json'):        # Use object repr_json method
            return obj.repr_json()
        else:
            return json.JSONEncoder.default(self, obj)


# https://stackoverflow.com/a/529466/1486966
def reverse_enumerate(L):
   for index in reversed(range(len(L))):
      yield index, L[index]


def hash_color(hash):
    global _hashes_fg, _hashes_bg

    if hash not in _hashes_fg:
        _hashes_fg[hash] = rand_fg()
        _hashes_bg[hash] = rand_bg()

    return colorize(hash, rgb=_hashes_fg[hash], bg=_hashes_bg[hash])


def rand_fg():
    r = random.randrange(0,0x7F) + 0x80
    g = random.randrange(0,0x7F) + 0x80
    b = random.randrange(0,0x7F) + 0x80
    return (r << 16) | (g << 8) | b

def rand_bg():
    r = random.randrange(0,0x7F)
    g = random.randrange(0,0x7F)
    b = random.randrange(0,0x7F)
    return (r << 16) | (g << 8) | b