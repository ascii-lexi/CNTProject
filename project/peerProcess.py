#!/usr/bin/python3
from socket import *
from dataclasses import dataclass
import math, threading, time, sys, struct

# I am going to make a Peer class incase I want helper functions later
@dataclass
class Peer:
    id: int
    host: str
    port: int
    hasFile: bool
# Create lock for log file
log_lock = threading.Lock()

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
            peers.append(Peer(int(peerID), hostname, int(listening_port), hasFile == 1))
    
    return peers

# Handshake Formatting
header = b"P2PFILESHARINGPROJ"
def pack_handshake(myPeerID):
    return header + b"\x00" * 10 + struct.pack(">I", myPeerID)
def parse_handshake(handshake):
    header = handshake[:18]
    peerID = struct.unpack(">I", handshake[28:32])[0]
    return header, peerID

# Message Helpers
def send_message(sock, type, payload=b""):
    sock.sendall(struct.pack(">IB", 1 + len(payload), type) + payload)

def read_message(sock):
    length = struct.unpack(">I", recv_exact(sock,4))[0]
    body = recv_exact(sock, length)
    return body[0], body[1:]
# Determine which peer process is being run from the command line arg
try:
    myPeerID: int = int(sys.argv[1])
except:
    print("Invalid peerID")
    sys.exit()
print("Peer ID: " + str(myPeerID))


# Parse Cfg
cfg = parse_common()
#print(cfg)
peers = parse_peerinfo()
#print(peers)

# Create log file object
logFilePath = "./log_peer_" + str(myPeerID) + ".log"
logFile = open(logFilePath, "w")

# Make Peer lists for before and after my ID
peers_before = []
peers_after = []
my_peer: Peer
for peer in peers:
    if(peer.id < myPeerID):
        peers_before.append(peer)
    elif(peer.id == myPeerID):
        my_peer = peer
    else:
        peers_after.append(peer)

# Bind + listen for TCP knocks
socket_connections = {}
listen_socket = socket(AF_INET, SOCK_STREAM)
listen_socket.bind(('', my_peer.port))
listen_socket.listen()

# For peers before me:
#   connect, send pack_handshake(), parse_handshake(recv_exact(32)), verify, log "makes a connection", add socket to socket_connections
for peer in peers_before:
    peerSock = socket(AF_INET, SOCK_STREAM)
    print("Connecting to (host, sock)" + peer.host + " " + str(peer.port))
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
   
