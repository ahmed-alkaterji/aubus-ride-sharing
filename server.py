
import socket
import threading
from client_handler import process_client
from database import initialize_database

SERVER_HOST = "127.0.0.1" #this is the fixed ip and port
SERVER_PORT = 5050
SERVER_ADDRESS = (SERVER_HOST, SERVER_PORT) #address is both port and ip

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #ipv4 socket creation, for tcp
server_socket.bind(SERVER_ADDRESS) #binding so server listens on this address and reserves it ( if bind fails pick another port)

initialize_database() #calls DB to either create or use the one available

server_socket.listen()
print(f"[SERVER STARTED] Listening on {SERVER_HOST}:{SERVER_PORT}") # just to confirm 

def run_server():
    while True:
        client_conn, client_addr = server_socket.accept() #waits for client to connect , returns socket just for that client and the ip,port of the client
        print(f"[NEW CLIENT] {client_addr} connected")
        thread = threading.Thread( #every client gets dedicated thread
            target=process_client, #It receives JSON requests from the client, checks the action (login/signup/matching/chat), interacts with the database, and sends a JSON response back.
            args=(client_conn, client_addr),
            daemon=True) #if close the server, thread auto die
        thread.start()
        print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")

if __name__ == "__main__":
    run_server()