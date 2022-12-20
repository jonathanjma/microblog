from datetime import datetime
from hashlib import md5
from time import time
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login
import jwt, json, re
from app.search import add_to_index, remove_from_index, query_index

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

likes = db.Table('likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'))
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))

    posts = db.relationship('Post', backref='author', lazy='dynamic')
    about_me = db.Column(db.String(140))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')

    post_likes = db.relationship(
        'Post', secondary=likes, primaryjoin=(likes.c.user_id == id),
        backref=db.backref('likes_on_post', lazy='dynamic'), lazy='dynamic')

    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id',
                                    backref='sender', lazy='dynamic')
    messages_received = db.relationship('Message', foreign_keys='Message.recipient_id',
                                        backref='recipient', lazy='dynamic')
    last_message_read_time = db.Column(db.DateTime)

    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    __type__ = 'User'

    def get_mention_name(self):
        if len(self.username.split()) > 1:
            return self.username.replace(' ', '')
        else:
            return self.username

    def get_posts(self):
        return self.posts.filter_by(parent_id=None)

    def get_comments(self):
        return self.posts.filter(Post.parent_id.isnot(None))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(digest, size)

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).count() > 0

    def followers(self):
        return self.followed.filter(followers.c.followed_id == id)

    def followed_posts(self):
        followed = Post.query.join(
            followers, (followers.c.followed_id == Post.user_id)).filter(
            followers.c.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.timestamp.desc())

    def like_post(self, post):
        if not self.is_post_liked(post):
            self.post_likes.append(post)

    def unlike_post(self, post):
        if self.is_post_liked(post):
            self.post_likes.remove(post)

    def is_post_liked(self, post):
        return self.post_likes.filter(likes.c.post_id == post.id).count() > 0

    def new_messages(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        return Message.query.filter_by(recipient=self).filter(
            Message.timestamp > last_read_time).count()

    def add_notification(self, name, data):
        self.notifications.filter_by(name=name).delete()
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256').decode('utf-8')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)

    def __repr__(self):
        return '<User {}>'.format(self.username)

def mention_user_filter(match):
    for user in User.query.all():
        if user.get_mention_name() == match:
            return user

@login.user_loader
def load_user(id):
    return User.query.get(int(id))

class SearchableMixin(object):
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return cls.query.filter_by(id=0), 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        return cls.query.filter(cls.id.in_(ids)).order_by(
            db.case(when, value=cls.id)), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in cls.query:
            add_to_index(cls.__tablename__, obj)

db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)

class Post(SearchableMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    language = db.Column(db.String(5))

    parent_id = db.Column(db.Integer, db.ForeignKey('post.id'))

    comment = db.relationship('Post', remote_side='Post.id',
        backref=db.backref('comments', lazy='dynamic'))

    user_likes = db.relationship(
        'User', secondary=likes, primaryjoin=(likes.c.post_id == id),
        backref=db.backref('liked_posts', lazy='dynamic'), lazy='dynamic')

    __searchable__ = ['body']
    __type__ = 'Post'

    def is_comment(self):
        return self.parent_id is not None

    def get_comment_parent(self):
        if self.is_comment():
            return Post.query.get(self.parent_id)

    def display_body_data(self):
        if self.body.count('@') >= 1:
            post_data = self.parse_mentions()
            parsed_post, users = post_data
            post = ''
            for segment in parsed_post:
                post += segment
            print(post)
            if post != self.body:
                raise RuntimeError('Mention parse error: post disagreement' \
                                   '\nExpected: ' + self.body + '\nActual: ' + post)
            print(users)
        else:
            post_data = self.body
        print(post_data)
        return post_data

    def parse_mentions(self):
        print()
        regex_pattern = re.compile(r"\w+(?:'\w+)*|[^\w]")
        matches = regex_pattern.findall(self.body)

        processed = 0
        post_segments = []
        users_dict = {}
        word_after = 0

        print(matches)
        print()

        for i in range(1, len(matches)):

            if matches[i-1] == '@':
                user_query = mention_user_filter(matches[i])

                if user_query is not None:
                    print('user= ' + user_query.username)
                    users_dict['@'+matches[i]] = user_query.username

                    if processed == 0:
                        split_indexes = [i-1,i+1]
                        split_list = [matches[i : j]
                                      for i, j in zip([0] + split_indexes, split_indexes + [None])]
                        print(split_list)

                        for segment in split_list:
                            post_segments.append("".join(segment))
                    else:
                        split_indexes = [word_after,i-1,i+1]
                        split_list = [matches[i : j]
                                      for i, j in zip([0] + split_indexes, split_indexes + [None])]
                        print(split_list)

                        post_segments.pop()
                        for j in range(1, len(split_list)):
                            post_segments.append("".join(split_list[j]))

                    processed += 1
                    word_after = i + 1

                    print(post_segments)
                    print()

                else:
                    print('User does not exist')

        if len(post_segments) == 0:
            post_segments = self.body
        return post_segments, users_dict

    def __repr__(self):
        return '<Post {}>'.format(self.body)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def __repr__(self):
        return '<Message {}>'.format(self.body)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.Float, index=True, default=time)
    payload_json = db.Column(db.Text)

    def get_data(self):
        return json.loads(str(self.payload_json))

    def __repr__(self):
        return '<Notification {}>'.format(self.get_data())