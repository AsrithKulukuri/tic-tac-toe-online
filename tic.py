from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
import random

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///scores.db'
db = SQLAlchemy(app)
socketio = SocketIO(app)


class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    wins = db.Column(db.Integer, default=0)


with app.app_context():
    db.create_all()

waiting_player = None
waiting_player_name = None
games = {}


def create_new_board():
    return [''] * 9


def check_winner(board):
    combos = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6)
    ]
    for a, b, c in combos:
        if board[a] != '' and board[a] == board[b] == board[c]:
            return board[a]
    if '' not in board:
        return 'draw'
    return None


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('join')
def handle_join(data):
    global waiting_player, waiting_player_name
    name = data['name']
    if waiting_player is None:
        waiting_player = request.sid
        waiting_player_name = name
        emit('waiting', {'message': 'Waiting for another player...'})

        def ai_join():
            global waiting_player, waiting_player_name
            if waiting_player:
                room = f"room_{waiting_player}_ai"
                join_room(room, sid=waiting_player)
                games[room] = {
                    'players': [waiting_player, 'ai'],
                    'names': {waiting_player: waiting_player_name, 'ai': 'Computer'},
                    'board': create_new_board(),
                    'turn': random.choice([waiting_player, 'ai']),
                    'scores': {waiting_player: 0, 'ai': 0}
                }
                socketio.emit('start_game', {
                    'room': room,
                    'symbols': {waiting_player: 'X', 'ai': 'O'},
                    'turn': games[room]['turn'],
                    'names': games[room]['names'],
                    'scores': games[room]['scores'],
                    'board': games[room]['board']
                }, room=waiting_player)

                # Fix: if AI starts first, make its move
                if games[room]['turn'] == 'ai':
                    socketio.sleep(1)
                    make_ai_move(room)

                waiting_player = None
                waiting_player_name = None

        socketio.start_background_task(lambda: socketio.sleep(10) or ai_join())
    else:
        room = f"room_{waiting_player}_{request.sid}"
        join_room(room, sid=waiting_player)
        join_room(room)
        games[room] = {
            'players': [waiting_player, request.sid],
            'names': {waiting_player: waiting_player_name, request.sid: name},
            'board': create_new_board(),
            'turn': random.choice([waiting_player, request.sid]),
            'scores': {waiting_player: 0, request.sid: 0}
        }
        socketio.emit('start_game', {
            'room': room,
            'symbols': {waiting_player: 'X', request.sid: 'O'},
            'turn': games[room]['turn'],
            'names': games[room]['names'],
            'scores': games[room]['scores'],
            'board': games[room]['board']
        }, room=room)
        waiting_player = None
        waiting_player_name = None


@socketio.on('make_move')
def handle_move(data):
    room = data['room']
    index = data['index']
    game = games.get(room)

    if not game or request.sid != game['turn']:
        return

    symbol = 'X' if request.sid == game['players'][0] else 'O'
    if game['board'][index] == '':
        game['board'][index] = symbol
        winner = check_winner(game['board'])

        if winner in ('X', 'O'):
            winning_player = game['players'][0] if winner == 'X' else game['players'][1]
            losing_player = game['players'][1] if winner == 'X' else game['players'][0]
            game['scores'][winning_player] += 1

            winner_name = game['names'][winning_player]
            score = Score.query.filter_by(name=winner_name).first()
            if not score:
                score = Score(name=winner_name, wins=1)
                db.session.add(score)
            else:
                score.wins += 1
            db.session.commit()

            socketio.emit('game_over', {
                'winner': winning_player,
                'loser': losing_player,
                'scores': game['scores'],
                'board': game['board']
            }, room=room)

            game['board'] = create_new_board()
            game['turn'] = random.choice(game['players'])
        elif winner == 'draw':
            socketio.emit('draw', room=room)
            game['board'] = create_new_board()
            game['turn'] = random.choice(game['players'])
        else:
            game['turn'] = game['players'][0] if game['turn'] == game['players'][1] else game['players'][1]

        socketio.emit('update_board', {
            'board': game['board'],
            'turn': game['turn'],
            'scores': game['scores']
        }, room=room)

        if game['turn'] == 'ai':
            make_ai_move(room)


def make_ai_move(room):
    game = games[room]
    available = [i for i, v in enumerate(game['board']) if v == '']
    if available:
        idx = random.choice(available)
        game['board'][idx] = 'O'
        winner = check_winner(game['board'])

        if winner in ('X', 'O'):
            winning_player = game['players'][0] if winner == 'X' else 'ai'
            losing_player = 'ai' if winning_player != 'ai' else game['players'][0]
            game['scores'][winning_player] += 1

            socketio.emit('game_over', {
                'winner': winning_player,
                'loser': losing_player,
                'scores': game['scores'],
                'board': game['board']
            }, room=room)

            game['board'] = create_new_board()
            game['turn'] = random.choice(game['players'])
        elif winner == 'draw':
            socketio.emit('draw', room=room)
            game['board'] = create_new_board()
            game['turn'] = random.choice(game['players'])
        else:
            game['turn'] = game['players'][0]

        socketio.emit('update_board', {
            'board': game['board'],
            'turn': game['turn'],
            'scores': game['scores']
        }, room=room)


@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    message = data['message']
    name = data['name']
    socketio.emit('receive_message', {
        'name': name,
        'message': message
    }, room=room)


@socketio.on('disconnect')
def handle_disconnect():
    global waiting_player, waiting_player_name
    if request.sid == waiting_player:
        waiting_player = None
        waiting_player_name = None
    else:
        for room, game in list(games.items()):
            if request.sid in game['players']:
                other_player = [p for p in game['players']
                                if p != request.sid][0]
                emit('opponent_left', room=other_player)
                del games[room]
                break


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
