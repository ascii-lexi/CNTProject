#!/usr/bin/python3
from socket import *
from dataclasses import dataclass
import math, threading, time

# I am going to make a Peer class incase I want helper functions later
@dataclass
class Peer:
    id: int
    host: str
    port: int
    hasFile: bool
# Create lock for log file
log_lock = threading.Lock()

def log(f, msg):
    with log_lock:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {msg}\n")
        f.flush()

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

cfg = parse_common()
print(cfg)
peers = parse_peerinfo()
print(peers)

serverPort = 12000
serverSocket = socket(AF_INET,SOCK_STREAM)

# .listen(1) mean max 1 queued connection
serverSocket.bind(('',serverPort))
serverSocket.listen(1)
print('The server is ready to receive')

serverName = 'localhost'
serverPort = 12000
clientSocket = socket(AF_INET, SOCK_STREAM)
# SOCK_STREAM = TCP

clientSocket.connect((serverName,serverPort))
connectionSocket, addr = serverSocket.accept()

print("sending data...")
clientSocket.send("12345".encode())
clientSocket.send("6789!".encode())

sentence = recv_exact(connectionSocket, 10)
connectionSocket.send(sentence)
connectionSocket.close()


modifiedSentence = clientSocket.recv(1024)
print('From Server: ', modifiedSentence.decode())
clientSocket.close()

