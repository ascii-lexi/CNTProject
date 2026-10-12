import socket

# Server side
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # avoids "address already in use" on restart
srv.bind(("localhost", 6001))
srv.listen()
conn, addr = srv.accept()       # blocks until someone connects; conn is a NEW socket for that peer
data = conn.recv(1024)          # blocks; returns b"" if the other side closed
conn.sendall(data)

# Client side
c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
c.connect(("localhost", 6001))
c.sendall(b"hello")
print(c.recv(1024))