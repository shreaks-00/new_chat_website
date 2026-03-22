from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room, send, emit
import os 
from datetime import datetime
import re
import threading
import time

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'yaper-secret-99-prod')
# Allow all origins for now; can be restricted to the Netlify URL once deployed
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10485760, async_mode='eventlet')

room_info = {} # Maps room_name -> {'is_private': bool, 'password': str, 'limit': int, 'users': {username: dict}}
room_history = {} # Stores latest 50 messages per room
session_users = {} # Maps connections: {sid: {'username': 'u', 'room': 'r', 'color': 'color'}}
disconnect_timers = {} # Maps (room, username) -> Timer

VIBRANT_COLORS = [
    '#ff4757', '#2ed573', '#1e90ff', '#ffa502', '#3742fa', 
    '#eccc68', '#70a1ff', '#7bed9f', '#ff6b81', '#5352ed',
    '#f0932b', '#eb4d4b', '#6ab04c', '#4834d4', '#be2edd'
]

def filter_profanity(text):
    bad_words = ['fuck', 'shit', 'bitch', 'asshole', 'crap']
    for word in bad_words:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        text = pattern.sub('*'*len(word), text)
    return text

def broadcast_room_users(room):
    if room in room_info:
        users_list = [{'name': u, 'color': room_info[room]['users'][u].get('color', '#000000')} for u in room_info[room]['users']]
        socketio.emit('room_users', users_list, to=room)

def update_room_list(to=None):
    rooms_data = [{'name': r, 'private': room_info[r].get('is_private', False)} for r in room_info.keys()]
    if to:
        socketio.emit('room_list', rooms_data, to=to)
    else:
        socketio.emit('room_list', rooms_data)

@app.route('/')
def landing():
    return send_from_directory('frontend', 'index.html')

@app.route('/chat')
def chat():
    return send_from_directory('frontend', 'chat.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('frontend', path)

@socketio.on('connect')
def handle_connect(auth=None):
    print(f"Client connected: {request.sid}")
    update_room_list(to=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    user_info = session_users.get(sid)
    if user_info:
        username = user_info['username']
        room = user_info['room']
        
        def remove_user_later():
            with app.app_context():
                if room in room_info and username in room_info[room]['users']:
                    # Check if the user hasn't reconnected (updated SID)
                    if room_info[room]['users'][username].get('sid') == sid:
                        del room_info[room]['users'][username]
                        broadcast_room_users(room)
                        if len(room_info[room]['users']) == 0:
                            if room in room_info and len(room_info[room]['users']) == 0:
                                del room_info[room]
                        update_room_list()
                        send(f"{username} has disconnected.", to=room)
                disconnect_timers.pop((room, username), None)

        timer = threading.Timer(60.0, remove_user_later)
        disconnect_timers[(room, username)] = timer
        timer.start()
        
        if sid in session_users:
            del session_users[sid]

@socketio.on('create_room')
def on_create_room(data):
    room = data['room'].strip()
    if not room:
        emit('join_error', {'error': 'Room name cannot be empty!'})
        return
    if room in room_info:
        emit('join_error', {'error': 'Room already exists!'})
        return
    room_info[room] = {
        'is_private': data.get('is_private', False),
        'password': data.get('password', ''),
        'limit': int(data.get('limit', 10)),
        'users': {}
    }
    emit('create_success', {'room': room})
    update_room_list()

@socketio.on('join')
def on_join(data):
    username = data['username'].strip()
    room = data['room'].strip()
    password = data.get('password', '')
    color = data.get('color', '#000000')
    
    if not username or not room:
        emit('join_error', {'error': 'Username and room cannot be empty!'})
        return
    if room not in room_info:
        emit('join_error', {'error': f"Room '{room}' doesn't exist!"})
        return
        
    info = room_info[room]
    
    if info['is_private'] and info['password'] != password:
        emit('join_error', {'error': 'Incorrect password!'})
        return
        
    # Auto-assign unique color if not set or already taken
    current_user_colors = [u.get('color') for u in info['users'].values()]
    if username in info['users']:
        color = info['users'][username].get('color')
    else:
        # Pick the first color not currently in use
        available_colors = [c for c in VIBRANT_COLORS if c not in current_user_colors]
        color = available_colors[0] if available_colors else VIBRANT_COLORS[len(info['users']) % len(VIBRANT_COLORS)]
    if len(info['users']) >= info['limit'] and username not in info['users']:
        emit('join_error', {'error': 'Room is full!'})
        return
        
    # Reconnection handling
    timer = disconnect_timers.pop((room, username), None)
    is_reconnect = False
    if timer:
        timer.cancel()
        is_reconnect = True

    join_room(room)
    info['users'][username] = {'color': color, 'sid': request.sid}
    session_users[request.sid] = {'username': username, 'room': room, 'color': color}
    
    update_room_list()
    broadcast_room_users(room)

    history = room_history.get(room, [])
    emit('chat_history', history)
    if not is_reconnect:
        send(f"{username} has entered.", to=room)

@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    if room in room_info and username in room_info[room]['users']:
        if room_info[room]['users'][username].get('sid') == request.sid:
            del room_info[room]['users'][username]
            broadcast_room_users(room)
            if len(room_info[room]['users']) == 0:
                del room_info[room]
            update_room_list()
    if request.sid in session_users:
        del session_users[request.sid]
    send(f"{username} has left.", to=room)

@socketio.on('typing')
def handle_typing(data):
    user_info = session_users.get(request.sid)
    if user_info:
        emit('typing', {'user': user_info['username'], 'is_typing': data.get('is_typing', True)}, to=user_info['room'], include_self=False)

@socketio.on('message')
def handle_message(data):
    user_info = session_users.get(request.sid)
    if not user_info: return
    room = user_info['room']
    raw_msg = data['msg']
    if data.get('type', 'text') == 'text':
        raw_msg = filter_profanity(raw_msg)
    import uuid
    msg_id = str(uuid.uuid4())
    msg_obj = {
        'id': msg_id, 'msg': raw_msg, 'user': user_info['username'], 
        'color': user_info.get('color', '#000000'), 'type': data.get('type', 'text'),
        'timestamp': datetime.now().strftime("%I:%M %p"), 'seen_by': []
    }
    if room not in room_history: room_history[room] = []
    room_history[room].append(msg_obj)
    if len(room_history[room]) > 50: room_history[room].pop(0)
    emit('message', msg_obj, to=room)

@socketio.on('mark_read')
def handle_mark_read(data):
    user_info = session_users.get(request.sid)
    if not user_info: return
    room = user_info['room']
    msg_id = data.get('msg_id')
    username = user_info['username']
    if room in room_history:
        for msg in room_history[room]:
            if msg.get('id') == msg_id:
                if username not in msg['seen_by']:
                    msg['seen_by'].append(username)
                    emit('message_status_update', {'msg_id': msg_id, 'seen_by': msg['seen_by']}, to=room)
                break


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)