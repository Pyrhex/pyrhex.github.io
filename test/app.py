from flask import Flask, render_template
from flask_socketio import SocketIO, send

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('test/index.html')

@socketio.on('message')
def handle_message(msg):
    print(f"Received message: {msg}")
    send(msg, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, port=8000, debug=True)