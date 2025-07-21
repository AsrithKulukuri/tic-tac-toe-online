from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from threading import Timer
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///scores.db'
db = SQLAlchemy(app)
socketio = SocketIO(app)

waiting_player = None
games = {}
ai_timers = {}


class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    score = db.Column(db.Integer, default=0)


with app.app_context():
    db.create_all()


def create_new_board():
    return ['' for _ in range(9)]


def check_winner(board):
    win_patterns = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8],  # rows
        [0, 3, 6], [1, 4, 7], [2, 5, 8],  # cols
        [0, 4, 8], [2, 4, 6]            # diagonals
    ]
    for pattern in win_patterns:
        if board[pattern[0]] and all(board[pattern[0]] == board[i] for i in pattern):
            return True
    return False


def ai_move(room):
    game = games.get(room)
    if not game:
        return
    board = game['board']
    empty_indices = [i for i, cell in enumerate(board) if cell == '']
    if not empty_indices:
        return
    index = random.choice(empty_indices)
    board[index] = 'o'
    game['turn'] = game['players'][0]  # back to human
    socketio.emit('move_made', {
        'index': index,
        'symbol': 'o',
        'turn': 'Your turn' if game['players'][0] == game['turn'] else 'Opponent\'s turn'
    }, room=room)
    if check_winner(board):
        update_score(game['players'][1])  # AI is player 2
        socketio.emit('game_over', {'message': f'Computer wins!'}, room=room)
        reset_game(room)


def reset_game(room):
    game = games.get(room)
    if game:
        game['board'] = create_new_board()
        game['turn'] = game['players'][0]
        socketio.emit('reset_board', room=room)


def update_score(name):
    player = Score.query.filter_by(name=name).first()
    if not player:
        player = Score(name=name, score=1)
    else:
        player.score += 1
    db.session.add(player)
    db.session.commit()


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    global waiting_player
    player_sid = request.sid

    if waiting_player and waiting_player != player_sid:
        room = f"room_{waiting_player}_{player_sid}"
        join_room(room)
        join_room(room, sid=waiting_player)

        games[room] = {
            'players': [waiting_player, player_sid],
            'board': create_new_board(),
            'turn': waiting_player
        }

        emit('start_game', {
            'room': room,
            'symbol': 'x',
            'opponent': 'Opponent',
            'scores': get_scores()
        }, room=waiting_player)
        emit('start_game', {
            'room': room,
            'symbol': 'o',
            'opponent': 'Opponent',
            'scores': get_scores()
        }, room=player_sid)

        waiting_player = None
        if room in ai_timers:
            ai_timers[room].cancel()
            del ai_timers[room]
    else:
        waiting_player = player_sid
        emit('waiting', {
             'message': 'Waiting for an opponent or AI to join...'})
        room = f"room_ai_{player_sid}"
        timer = Timer(10.0, start_ai_game, [player_sid, room])
        ai_timers[room] = timer
        timer.start()


def start_ai_game(player_sid, room):
    join_room(room)
    games[room] = {
        'players': [player_sid, 'AI'],
        'board': create_new_board(),
        'turn': player_sid
    }
    socketio.emit('start_game', {
        'room': room,
        'symbol': 'x',
        'opponent': 'Computer',
        'scores': get_scores()
    }, room=player_sid)


@socketio.on('make_move')
def handle_move(data):
    room = data['room']
    index = data['index']
    player = request.sid
    game = games.get(room)

    if not game or player != game['turn']:
        return

    board = game['board']
    if board[index] != '':
        return

    symbol = 'x' if player == game['players'][0] else 'o'
    board[index] = symbol

    next_turn = game['players'][1] if player == game['players'][0] else game['players'][0]
    game['turn'] = next_turn

    emit('move_made', {
        'index': index,
        'symbol': symbol,
        'turn': 'Your turn' if game['turn'] == player else 'Opponent\'s turn'
    }, room=room)

    if check_winner(board):
        update_score(player if symbol == 'x' else 'AI')
        emit('game_over', {'message': 'You won!' if symbol ==
             'x' else 'You lost!'}, room=room)
        reset_game(room)
        return

    if next_turn == 'AI':
        Timer(1.0, ai_move, [room]).start()


def get_scores():
    players = Score.query.all()
    return {p.name: p.score for p in players}


if __name__ == '__main__':
    socketio.run(app)
