#!/usr/bin/python3
from sys import byteorder
from socket import *
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import math, threading, time, sys, struct, random

#Message Type Enum
class MsgType(Enum):
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOTINTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7


# I am going to make a Peer class incase I want helper functions later
@dataclass
class Peer:
    id: int
    host: str
    port: int
    hasFile: bool

    # connection state, filled in once connected
    sock: Optional[socket.socket] = field(default=None, repr=False)

    # We need default_factory because we need seperate locks for each peer
    send_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # their pieces; set to make_bitfield(num_pieces) after the config is read
    bitfield: Optional[bytearray] = field(default=None, repr=False)

    # protocol state
    they_choke_me: bool = True        # we start out choked
    i_choke_them: bool = True
    they_interested: bool = False
    i_am_interested: bool = False
    outstanding: Optional[int] = None # piece index I've requested from them, if any

# Create locks
log_lock = threading.Lock()
state_lock = threading.Lock()
# Log formatting Helpers
def log(f, msg):
    with log_lock:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {msg}\n")
        f.flush()
def log_conn_to(f, myID, theirID):
    msg = "Peer " + str(myID) + " makes a connection to Peer " + str(theirID) + "."
    log(f, msg)
def log_conn_from(f, myID, theirID):
    msg = "Peer " + str(myID) + " is connected from Peer " + str(theirID) +"."
    log(f, msg)
def log_received_interested(f, myID, theirID):
    msg = "Peer " + str(myID) + " received the 'interested' message from " + str(theirID) + "."
    log(f,msg)
def log_received_not_interested(f, myID, theirID):
    msg = "Peer " + str(myID) + " received the 'not interested' message from " + str(theirID) + "."
    log(f,msg)
def log_unchoked_by(f, myID, theirID):
    msg = "Peer " + str(myID) + " is unchoked by " + str(theirID) + "."
    log(f,msg)
def log_choked_by(f, myID, theirID):
    msg = "Peer " + str(myID) + " is choked by " + str(theirID) + "."
    log(f,msg)
def log_downloaded(f, myID, theirID, index, totalCount):
    msg = "Peer " + str(myID) + " has downloaded the piece " + str(index) + " from " + str(theirID) + ". Now the number of pieces it has is " + str(totalCount)
    log(f, msg)
def log_have_from(f, myID, theirID, index):
    msg = "Peer " + str(myID) + " received the 'have' message from " + str(theirID) + " for the piece " + str(index)
    log(f, msg)
# helper function to fetch specific number of bytes (n) from socket
def recv_exact(sock, n: int):
    buf = b""
    while len(buf) < n: # fetch bytes until buffer has n bytes
        chunk = sock.recv(n-len(buf))

        if not chunk: # chunk == b"" if socket is closed
            raise ConnectionError("recv_exact: socket closed")
        buf += chunk # append recieved chunk to buffer
    return buf

def parse_common():
    common_cfg_dict = {}
    filePath = "./Common.cfg"
    # load all fields into dictionary
    with open(filePath,"r") as f:
        for line in f:
            line = line.strip()
            if not line: # Skip blank lines
                continue
            key, value = line.split()
            common_cfg_dict[key] = value
        
    # Convert the int fields to ints from strings
    for key in ("NumberOfPreferredNeighbors", "UnchokingInterval",
            "OptimisticUnchokingInterval", "FileSize", "PieceSize"):
            common_cfg_dict[key] = int(common_cfg_dict[key])
        
    #Do NumPieces calculation given in spec
    common_cfg_dict["NumPieces"] = math.ceil(common_cfg_dict["FileSize"]/common_cfg_dict["PieceSize"])
    return common_cfg_dict

# File order matters! 
def parse_peerinfo():
    filePath = "./PeerInfo.cfg"
    peers = []
    with open(filePath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            peerID, hostname, listening_port, hasFile = line.split()
            peers.append(Peer(int(peerID), hostname, int(listening_port), int(hasFile) == 1))
    
    return peers

# Load File for Sharing
def load_file():
    with open(f"peer_{myPeerID}/{cfg["FileName"]}", "rb") as f:
        data = f.read()
    piece_size = cfg["PieceSize"]
    num_pieces = cfg["NumPieces"]
    return {i: data[i*piece_size:(i+1)*piece_size] for i in range(num_pieces)}

# Handshake Formatting
header = b"P2PFILESHARINGPROJ"
def pack_handshake(myPeerID):
    return header + b"\x00" * 10 + struct.pack(">I", myPeerID)
def parse_handshake(handshake):
    header = handshake[:18]
    peerID = struct.unpack(">I", handshake[28:32])[0]
    return header, peerID

# Message Helpers
def send_message(peer, type: int, payload=b""):
    msg = struct.pack(">IB", 1 + len(payload), type.value) + payload
    with peer.send_lock:
        peer.sock.sendall(msg)

#Bitfield Helpers
def read_message(sock):
    length = struct.unpack(">I", recv_exact(sock,4))[0]
    body = recv_exact(sock, length)
    return body[0], body[1:]

def make_bitfield(num_pieces, full=False):
    bf = bytearray((num_pieces + 7) // 8)       # round up: 10 pieces -> 2 bytes, all zero
    if full:
        for i in range(num_pieces):
            set_piece(bf, i)                    # set one by one so spare bits stay 0
    return bf

def has_piece(bf, i):
    mask = 0b10000000 >> (i % 8)
    return (bf[i // 8] & mask) != 0

def set_piece(bf, i):
    mask = 0b10000000 >> (i % 8)
    bf[i // 8] |= mask                          # modifies bf in place

def count_pieces(bf):
    return sum(bin(byte).count("1") for byte in bf)   # count the 1-bits in each byte

def is_complete(bf, num_pieces):
    return count_pieces(bf) == num_pieces

def has_interesting(mine, theirs):
    # True if `theirs` has at least one piece that `mine` lacks
    return any(t & ~m for m, t in zip(mine, theirs))

def pick_piece(peer):
    num_pieces = cfg["NumPieces"]
    candidates = [i for i in range(num_pieces) if has_piece(peer.bitfield,i) and not has_piece(my_bitfield,i) and i not in requested]
    return random.choice(candidates) if candidates else None

# Connection handler
def handle_connection(peer):
    try:
        while True:
            mtype, payload = read_message(peer.sock)
            if   mtype == MsgType.BITFIELD.value:        on_bitfield(peer, payload)
            elif mtype == MsgType.INTERESTED.value:      on_interested(peer)
            elif mtype == MsgType.NOTINTERESTED.value:   on_not_interested(peer)
            elif mtype == MsgType.HAVE.value:            on_have(peer, payload)
            elif mtype == MsgType.CHOKE.value:           on_choke(peer)
            elif mtype == MsgType.UNCHOKE.value:         on_unchoke(peer)
            elif mtype == MsgType.REQUEST.value:         on_request(peer, payload)
            elif mtype == MsgType.PIECE.value:           on_piece(peer, payload)
    except ConnectionError:
        pass                                # remote closed; thread exits

# Interest Handeling
def on_bitfield(peer, payload):
    with state_lock:
        #peer.bitfield = Bitfield.from_bytes(payload, num_pieces)
        peer.bitfield = bytearray(payload)
        am_interested = has_interesting(my_bitfield, peer.bitfield)
        peer.i_am_interested = am_interested
    if (am_interested):
        send_message(peer, MsgType.INTERESTED)
    else:
        send_message(peer, MsgType.NOTINTERESTED)
def on_interested(peer):
    with state_lock: peer.they_interested = True
    log_received_interested(logFile,myPeerID,peer.id)        # "Peer X received the 'interested' message from Y."

    # TODO: replace with preferred/optimistic neighbor selection
    send_message(peer, MsgType.UNCHOKE)
    peer.i_choke_them = False

def on_not_interested(peer):
    with state_lock: peer.they_interested = False
    log_received_not_interested(logFile, myPeerID, peer.id)

def on_unchoke(peer):
    log_unchoked_by(logFile,myPeerID,peer.id)
    with state_lock:
        peer.they_choke_me = False
        i = pick_piece(peer)
        if i is not None: requested.add(i)
    if i is not None:
        send_message(peer, MsgType.REQUEST, struct.pack(">I", i))

def on_choke(peer):
    log_choked_by(peer.id)
    with state_lock: peer.they_choke_me = True
    # any outstanding request will never be answered; remove it from `requested`
    if (peer.outstanding is not None):
        requested.remove(peer.outstanding)
        peer.outstanding = None
    
def on_request(peer, payload):
    i = struct.unpack(">I", payload)[0]
    with state_lock:
        if peer.i_choke_them: return            # ignore requests from choked neighbors
        data = piece_index[i]
    send_message(peer, MsgType.PIECE, struct.pack(">I", i) + data)

def on_piece(peer, payload):
    i = struct.unpack(">I", payload[:4])[0]
    data = payload[4:]
    with state_lock:
        piece_index[i] = data
        set_piece(my_bitfield, i)
        requested.discard(i)
        count = count_pieces(my_bitfield)
        complete = is_complete(my_bitfield, cfg["NumPieces"])
    log_downloaded(logFile, myPeerID, peer.id, i, count)
    # next steps: broadcast `have`, update interest, request again
    for broadcastPeer in peers:
        send_message(broadcastPeer, MsgType.HAVE, struct.pack(">I",i))
        print("My Bitfield: " + str(my_bitfield) + "\nTheir Bitfield (peer "+ str(broadcastPeer.id)+ "): " + str(broadcastPeer.bitfield))
        if (not has_interesting(my_bitfield,broadcastPeer.bitfield) and broadcastPeer.i_am_interested):
            send_message(broadcastPeer, MsgType.NOTINTERESTED)
            broadcastPeer.i_am_interested = False
    if not peer.they_choke_me and pick_piece(peer) is not None:
        send_message(peer, MsgType.REQUEST, struct.pack(">I", pick_piece(peer)))

def on_have(peer, payload):
    index = struct.unpack(">I",payload)[0]
    set_piece(peer.bitfield, index)
    log_have_from(logFile, myPeerID, peer.id, index)
    am_interested = has_interesting(my_peer.bitfield, peer.bitfield)
    if am_interested:
        peer.i_am_interested = True
        send_message(peer, MsgType.INTERESTED, struct.pack(">I", index))
# Determine which peer process is being run from the command line arg
try:
    myPeerID: int = int(sys.argv[1])
except:
    print("Invalid peerID")
    sys.exit()
print("My Peer ID: " + str(myPeerID))


# Parse Cfg
cfg = parse_common()
#print(cfg)
peers = parse_peerinfo()
#print(peers)

# Make Peer lists for before and after my ID
peers_before = []
peers_after = []
my_peer: Peer

for peer in peers:
    peer.bitfield = make_bitfield(cfg["NumPieces"])
    if(peer.id < myPeerID):
        peers_before.append(peer)
    elif(peer.id == myPeerID):
        my_peer = peer
    else:
        peers_after.append(peer)
peers = peers_before + peers_after

# Create bitfield
#print("I have file: " + str(my_peer.hasFile))
my_bitfield = make_bitfield(cfg["NumPieces"] ,my_peer.hasFile)
piece_index = {}
if(my_peer.hasFile):
    piece_index=load_file()

# Create dict of requested pieces
requested = set()

# Create log file object
logFilePath = "./log_peer_" + str(myPeerID) + ".log"
logFile = open(logFilePath, "w")



# Bind + listen for TCP knocks
socket_connections = {}
listen_socket = socket(AF_INET, SOCK_STREAM)
listen_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
listen_socket.bind(('', my_peer.port))
listen_socket.listen()

# For peers before me:
#   connect, send pack_handshake(), parse_handshake(recv_exact(32)), verify, log "makes a connection", add socket to socket_connections
for peer in peers_before:
    peerSock = socket(AF_INET, SOCK_STREAM)
    peerSock.connect((peer.host, peer.port))

    peerSock.sendall(pack_handshake(myPeerID))
    theirHeader, theirPeerID = parse_handshake(recv_exact(peerSock,32))
    
    # Verify
    notValid = True
    for peer in peers_before:
        if(peer.id == theirPeerID and theirHeader == header):
            notValid = False
    if(notValid):
        print("Invalid connection to " + str(theirPeerID))
        sys.exit()

    log_conn_to(logFile, myPeerID, theirPeerID)
    socket_connections[theirPeerID] = peerSock
    

# For peers after me:
#   conn, addr = srv.accept(), send pack_handshake(), parse_handshake(recv_exact(32)), log "is connected from"
for i in range(len(peers_after)):
    peerSock, peerAddress = listen_socket.accept()
    peerHN, peerPort = peerAddress
    peerSock.sendall(pack_handshake(myPeerID))
    theirHeader, theirPeerID = parse_handshake(recv_exact(peerSock,32))
    # Verify
    notValid = True
    for peer in peers_after:
        if(peer.id == theirPeerID and theirHeader == header):
            notValid = False
    if(notValid):
        print("Invalid connection from " + str(theirPeerID))
        sys.exit()
    log_conn_from(logFile, myPeerID, theirPeerID)
    socket_connections[theirPeerID] = peerSock

#print(socket_connections)
# Add socket_connections to each peer obj
for peer in peers:
    #print(peer.id)
    peer.sock = socket_connections[peer.id]

# Send bitfield if non-zero
for peer in peers:
    #print(my_bitfield)
    if(count_pieces(my_bitfield) > 0):
        send_message(peer, MsgType.BITFIELD, bytes(my_bitfield))

# Start connection handler for each peer (excluding this peer)
for peer in peers:
    threading.Thread(target=handle_connection, args=(peer,), daemon=True).start()

# This keeps our background handler threads running until we implement shutdown logic   
while True:
    time.sleep(1)