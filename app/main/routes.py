from datetime import datetime
from flask import render_template, flash, redirect, url_for, request, g, \
    jsonify, current_app
from flask_login import current_user, login_required
from flask_babel import get_locale
from app import db, wa
from app.main.forms import EditProfileForm, PostForm, CommentForm, SearchForm, MessageForm, EmptyForm
from app.models import User, Post, Message, Notification
from googletrans import Translator
from app.main import bp

@bp.before_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        g.search_form = SearchForm()
    g.locale = str(get_locale())

@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = PostForm()
    if form.validate_on_submit():
        language = Translator().detect(form.post.data).lang
        post = Post(body=form.post.data, author=current_user, language=language)
        db.session.add(post)
        db.session.commit()
        flash('Your post is now live!')
        return redirect(url_for('main.index'))
    page = request.args.get('page', 1, type=int)
    posts = current_user.followed_posts().paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.index', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('index.html', title='Home', form=form,
                           posts=posts.items, next_url=next_url, prev_url=prev_url)

@bp.route('/explore')
@login_required
def explore():
    page = request.args.get('page', 1, type=int)
    posts = Post.query.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.explore', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.explore', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template("index.html", title='Explore', posts=posts.items,
                           next_url=next_url, prev_url=prev_url)

@bp.route('/user/<username>')
@login_required
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    show = request.args.get('show')

    if show is not None and current_user.username != username:
        return redirect(url_for('main.user', username=user.username))

    if show in [None, 'following', 'followers', 'likes', 'comments']:
        if show is None:
            items = user.get_posts().order_by(Post.timestamp.desc()).paginate(
                page, current_app.config['POSTS_PER_PAGE'], False)
            list_type = 'post'
            id = 1
        elif show == 'following':
            items = user.followed.order_by(User.username.asc()).paginate(
                page, current_app.config['POSTS_PER_PAGE'], False)
            list_type = 'user'
            id = 2
        elif show == 'followers':
            items = user.followers.order_by(User.username.asc()).paginate(
                page, current_app.config['POSTS_PER_PAGE'], False)
            list_type = 'user'
            id = 3
        elif show == 'likes':
            items = user.liked_posts.order_by(Post.timestamp.desc()).paginate(
                page, current_app.config['POSTS_PER_PAGE'], False)
            list_type = 'post'
            id = 4
        else:
            items = user.get_comments().order_by(Post.timestamp.desc()).paginate(
                page, current_app.config['POSTS_PER_PAGE'], False)
            list_type = 'post'
            id = 5

        if show is None:
            next_url = url_for('main.user', username=user.username, page=items.next_num) \
                if items.has_next else None
            prev_url = url_for('main.user', username=user.username, page=items.prev_num) \
                if items.has_prev else None
        else:
            next_url = url_for('main.user', username=user.username, show=show, page=items.next_num) \
                if items.has_next else None
            prev_url = url_for('main.user', username=user.username, show=show, page=items.prev_num) \
                if items.has_prev else None

        form = EmptyForm()
        return render_template('user.html', user=user, items=items.items, item_type=list_type, id=id,
                               next_url=next_url, prev_url=prev_url, form=form)
    else:
        return redirect(url_for('main.user', username=user.username))

@bp.route('/user/<username>/popup')
@login_required
def user_popup(username):
    user = User.query.filter_by(username=username).first_or_404()
    form = EmptyForm()
    return render_template('user_popup.html', user=user, form=form)

@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username, current_user.email)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        current_user.email = form.email.data
        db.session.commit()
        flash('Your changes have been saved.')
        return redirect(url_for('main.edit_profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
        form.email.data = current_user.email
    return render_template('edit_profile.html', title='Edit Profile', form=form)

@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=username).first()
        if user is None:
            flash('User {} not found.'.format(username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash('You cannot follow yourself!')
            return redirect(url_for('main.user', username=username))
        current_user.follow(user)
        db.session.commit()
        flash('You are following {}!'.format(username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))

@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=username).first()
        if user is None:
            flash('User {} not found.'.format(username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash('You cannot unfollow yourself!')
            return redirect(url_for('main.user', username=username))
        current_user.unfollow(user)
        db.session.commit()
        flash('You are not following {}.'.format(username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))

@bp.route('/post/<post_id>', methods=['GET', 'POST'])
@login_required
def post_info(post_id):
    page = request.args.get('page', 1, type=int)
    post = Post.query.filter_by(id=post_id).first_or_404()
    emp_form = EmptyForm()
    form = CommentForm()
    if form.validate_on_submit():
        language = Translator().detect(form.comment.data).lang
        comment = Post(body=form.comment.data, author=current_user, language=language, parent_id=post_id)
        db.session.add(comment)
        db.session.commit()
        flash('Your comment is now live!')
        return redirect(url_for('main.post_info', post_id=post_id))

    comments = post.comments.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.post_info', post_id=post_id, page=comments.next_num) \
        if comments.has_next else None
    prev_url = url_for('main.post_info', post_id=post_id, page=comments.prev_num) \
        if comments.has_prev else None
    return render_template('post_info.html', post=post, form=form, emp_form=emp_form,
                           comments=comments.items, next_url=next_url, prev_url=prev_url)

@bp.route('/like_post/<post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    form = EmptyForm()
    if form.validate_on_submit():
        post = Post.query.filter_by(id=post_id).first()
        if post is None:
            flash('Post {} not found.'.format(post))
            return redirect(url_for('main.index'))
        current_user.like_post(post)
        db.session.commit()
        flash('Post added to liked posts')
    return redirect(url_for('main.post_info', post_id=post_id))

@bp.route('/unlike_post/<post_id>', methods=['POST'])
@login_required
def unlike_post(post_id):
    form = EmptyForm()
    if form.validate_on_submit():
        post = Post.query.filter_by(id=post_id).first()
        if post is None:
            flash('Post {} not found.'.format(post))
            return redirect(url_for('main.index'))
        current_user.unlike_post(post)
        db.session.commit()
        flash('Post removed from liked posts')
    return redirect(url_for('main.post_info', post_id=post_id))

@bp.route('/post/<post_id>/likes_popup')
@login_required
def post_likes_popup(post_id):
    post = Post.query.filter_by(id=post_id).first_or_404()
    return render_template('post_likes_popup.html', users=post.likes_on_post)

@bp.route('/send_message/<recipient>', methods=['GET', 'POST'])
@login_required
def send_message(recipient):
    user = User.query.filter_by(username=recipient).first_or_404()
    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(author=current_user, recipient=user, body=form.message.data)
        db.session.add(msg)
        user.add_notification('unread_message_count', user.new_messages())
        db.session.commit()
        flash('Your message has been sent.')
        return redirect(url_for('main.user', username=recipient))
    return render_template('send_message.html', title='Send Message',
                           form=form, recipient=recipient)

@bp.route('/messages')
@login_required
def messages():
    current_user.last_message_read_time = datetime.utcnow()
    current_user.add_notification('unread_message_count', 0)
    db.session.commit()
    page = request.args.get('page', 1, type=int)
    messages = current_user.messages_received.order_by(
        Message.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.messages', page=messages.next_num) \
        if messages.has_next else None
    prev_url = url_for('main.messages', page=messages.prev_num) \
        if messages.has_prev else None
    return render_template('messages.html', messages=messages.items,
                           next_url=next_url, prev_url=prev_url)

@bp.route('/notifications')
@login_required
def notifications():
    since = request.args.get('since', 0.0, type=float)
    notifications = current_user.notifications.filter(
        Notification.timestamp > since).order_by(Notification.timestamp.asc())
    return jsonify([{
        'name': n.name,
        'data': n.get_data(),
        'timestamp': n.timestamp
    } for n in notifications])

@bp.route('/search')
@login_required
def search():
    if not g.search_form.validate():
        return redirect(url_for('main.explore'))
    from sqlalchemy.exc import ArgumentError
    posts = ""
    try:
        posts = Post.query.whoosh_search(g.search_form.q.data).all()
    except ArgumentError:
        pass
    return render_template('search.html', title='Search', posts=posts)
    # pagination check out https://pypi.org/project/paginate-whoosh/

    # page = request.args.get('page', 1, type=int)
    # posts, total = Post.search(g.search_form.q.data, page,
    #                            current_app.config['POSTS_PER_PAGE'])
    # next_url = url_for('main.search', q=g.search_form.q.data, page=page + 1) \
    #     if total > page * current_app.config['POSTS_PER_PAGE'] else None
    # prev_url = url_for('main.search', q=g.search_form.q.data, page=page - 1) \
    #     if page > 1 else None
    # return render_template('search.html', title='Search', posts=posts,
    #                        next_url=next_url, prev_url=prev_url)

# @bp.route('/reindex')
# @login_required
# def reindex():
#     wa.index_all(current_app)
#     flash('App reindexed')
#     return redirect(url_for('main.index'))

@bp.route("/translate", methods=['POST'])
@login_required
def translate_text():
    # emoji fix- edit gtoken.py line 164: change "len(text)" to "len(a)"
    dest = request.form['dest_language']
    if dest == "zh": dest = "zh-tw"
    #from googletrans import LANGUAGES as codes # all language codes
    return jsonify({'text': Translator().translate(
        text=request.form['text'],src=request.form['source_language'],dest=dest).text})