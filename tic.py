from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecret'
socketio = SocketIO(app, cors_allowed_origins='*')

# Serve index.html when visiting /


@app.route('/')
def index():
    return render_template('index.html')


# In-memory store of waiting players and game rooms
waiting_player = None
games = {}  # room -> {players: [sid1, sid2], board: [...], turn: sid}


def create_new_board():
    return ['' for _ in range(9)]  # empty 3x3 board


@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    global waiting_player
    if waiting_player is None:
        waiting_player = request.sid
        emit('waiting', {'message': 'Waiting for an opponent...'})
    else:
        # Match found
        room = f"room_{waiting_player}_{request.sid}"
        join_room(room, sid=waiting_player)
        join_room(room)
        games[room] = {
            'players': [waiting_player, request.sid],
            'board': create_new_board(),
            'turn': random.choice([waiting_player, request.sid])
        }
        socketio.emit('start_game', {
            'room': room,
            'symbol': 'X',
            'turn': games[room]['turn']
        }, room=waiting_player)
        socketio.emit('start_game', {
            'room': room,
            'symbol': 'O',
            'turn': games[room]['turn']
        }, room=request.sid)
        waiting_player = None


@socketio.on('make_move')
def handle_move(data):
    room = data['room']
    index = data['index']
    player = request.sid
    game = games.get(room)

    if not game or player != game['turn']:
        return  # ignore invalid moves

    if game['board'][index] != '':
        return  # already occupied

    symbol = 'X' if player == game['players'][0] else 'O'
    game['board'][index] = symbol
    # Switch turn
    game['turn'] = game['players'][0] if game['turn'] == game['players'][1] else game['players'][1]

    socketio.emit('update_board', {
        'board': game['board'],
        'turn': game['turn']
    }, room=room)


@socketio.on('disconnect')
def handle_disconnect():
    global waiting_player
    print(f"Client disconnected: {request.sid}")
    if waiting_player == request.sid:
        waiting_player = None

    # Clean up any games the player was part of
    for room, game in list(games.items()):
        if request.sid in game['players']:
            socketio.emit('opponent_left', room=room)
            del games[room]


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
