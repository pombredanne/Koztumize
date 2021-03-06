"""Koztumize routes."""
# -*- coding: utf-8 -*-

import os
import ldap
from flask import (render_template, request, redirect, url_for, jsonify,
                   session, flash)
from pynuts.document import InvalidId
from pynuts.rights import allow_if
from . import rights as Is
from .application import nuts
from .document import CourrierStandard
from .directives import Button
from .model import Users, UserRights, Rights, DB as db
from .helpers import NoPermission, get_last_commits


@nuts.app.route('/login', methods=('POST', ))
def login_post():
    """Test the user authentification."""
    username = request.form['login']
    password = request.form['passwd']
    user = nuts.ldap.search_s(
        nuts.app.config['LDAP_PATH'], ldap.SCOPE_ONELEVEL, "uid=%s" % username)
    if not user or not password:
        flash(u"Erreur : Les identifiants sont incorrects.", 'error')
        return render_template('login.html')
    try:
        nuts.ldap.simple_bind_s(user[0][0], password)
    except ldap.INVALID_CREDENTIALS:  # pragma: no cover
        flash(u"Erreur : Les identifiants sont incorrects.", 'error')
        return render_template('login.html')
    session["user"] = user[0][1]['cn'][0].decode('utf-8')
    session["usermail"] = user[0][1].get('mail', ["none"])[0].decode('utf-8')
    session["user_group"] = user[0][1].get(
        'o', ["none"])[0].decode('utf-8').lower()
    return redirect(url_for('index'))


@nuts.app.route('/logout')
@allow_if(Is.connected)
def logout():
    """Logout route."""
    session.clear()
    return render_template('login.html')


@nuts.app.route('/')
@allow_if(Is.connected)
def index():
    """The index displays all the available models."""
    model_path = nuts.app.config['MODELS']
    models = {
        category: os.listdir(os.path.join(model_path, category))
        for category in os.listdir(model_path)
        if not category.startswith(('_', '.'))}
    commits = get_last_commits()
    return render_template('index.html', models=models, commits=commits)


@nuts.app.route('/create/<document_type>', methods=('GET', 'POST'))
@allow_if(Is.connected)
def create_document(document_type=None):
    """
    The route which renders the form for document creation if method is GET

    If POST, create the document by giving its type and its name.

    """
    if request.method == 'GET':
        return render_template('document_form.html',
                               document_type=document_type)
    else:
        document_name = request.form['name']
        if not document_name.replace(" ", ""):
            flash('Veuillez saisir un nom pour votre document !'.decode(
                'utf8'), 'error')
            return render_template('document_form.html',
                                   document_type=document_type)
        for document in nuts.documents.values():
            if document_name in document.list_document_ids():
                flash('Un document porte déjà le même nom !'.decode('utf8'),
                      'error')
                return render_template('document_form.html',
                                       document_type=document_type)
        document = nuts.documents[document_type]
        try:
            document.create(document_name=document_name,
                            author_name=session.get('user'),
                            author_email=session.get('usermail'))
        except InvalidId:
            flash('Erreur, veuillez ne pas mettre de "/" dans le nom de votre '
                  'document.', 'error')
            return redirect(url_for(
                'create_document', document_type=document_type))
        db.session.add(Rights(document_name, session.get('user')))
        db.session.add(
            UserRights(document_name, session.get('user'), True, True))
        db.session.commit()
        return redirect(url_for('edit',
                                document_type=document_type,
                                document_name=document_name))


@nuts.app.route('/edit/<document_type>/<path:document_name>')
@allow_if(Is.connected)
@allow_if(Is.document_writable, NoPermission)
def edit(document_name=None, document_type=None):
    """Render the page for document edition."""
    return render_template(
        'edit.html', document_type=document_type, document_name=document_name)


@nuts.app.route('/view/<document_type>/<path:document_name>/<version>')
@allow_if(Is.connected)
@allow_if(Is.document_readable, NoPermission)
def view(document_name=None, document_type=None, version=None):
    """Render the page for document view."""
    return render_template('view.html', document_type=document_type,
                           document_name=document_name, version=version)


@nuts.app.route('/documents')
@allow_if(Is.connected)
def documents():
    """Render the list of all the version of existing documents."""
    document_classes = nuts.documents.values()
    document_list = []
    for document_class in document_classes:
        document_ids = document_class.list_document_ids()
        for document_id in document_ids:
            users_read = []
            users_write = []
            allowed_users = UserRights.query.filter_by(
                document_id=document_id).all()
            for user in allowed_users:
                if user.read:
                    users_read.append(user.user_id)
                if user.write:
                    users_write.append(user.user_id)
            document_list.append({'document_id': document_id,
                'users_read': users_read,
                'users_write': users_write,
                'type': document_class.type_name,
                'history': list(document_class(document_id).history)})
    return render_template('documents.html',
                           document_list=document_list)


@nuts.app.route('/model/<document_type>/<path:document_name>/head')
@nuts.app.route('/model/<document_type>/<path:document_name>/<version>')
@allow_if(Is.connected)
def model(document_name=None, document_type=None, version=None):
    """The route which renders the ReST model parsed in HTML."""
    document = nuts.documents[document_type]
    editable = False if version else True
    return document.html('model.html', editable=editable,
                         document_name=document_name, version=version)


@nuts.app.route('/pdf/<document_type>/<path:document_name>')
@nuts.app.route('/pdf/<document_type>/<path:document_name>/<version>')
@allow_if(Is.connected)
def pdf(document_type, document_name, version=None):
    """The route which returns a document as PDF."""
    document = nuts.documents[document_type]
    return document.download_pdf(document_name=document_name,
                                 filename=document_name + '.pdf',
                                 version=version)


# AJAX routes
@nuts.app.route('/create_rights', methods=('POST',))
def create_rights():
    """Grant specific rights to a document."""
    document_id = request.form['document_id']
    user_id = request.form['user_id']
    read = request.form['read']
    write = request.form['write']
    db.session.add(UserRights(document_id, user_id, read, write))
    db.session.commit()
    return jsonify({'user_id': user_id, 'read': read, 'write': write})


@nuts.app.route('/read_rights', methods=('POST',))
def read_rights():
    """Render a list of users and their rights for the current document."""
    document_id = request.form['document_id']
    users = Users.query.all()
    allowed_users = UserRights.query.filter_by(document_id=document_id).all()
    allowed_user_ids = [user.user_id for user in allowed_users]
    owner = Rights.query.filter_by(document_id=document_id).first().owner
    available_users = [
        user.fullname for user in users if user.employe and
        user.fullname not in allowed_user_ids]
    return render_template('rights.html', document_name=document_id,
                           users=users, allowed_users=allowed_users,
                           owner=owner, available_users=available_users)


@nuts.app.route('/update_rights', methods=('POST',))
def update_rights():
    """Modify rights for a document."""
    document_id = request.form['document_id']
    user_id = request.form['user_id']
    rights = request.form['rights']
    if rights == 'r':
        read = True
        write = False
        label_rights = 'Lecture'
    elif rights == 'w':
        read = False
        write = True
        label_rights = 'Ecriture'
    else:
        read = True
        write = True
        label_rights = 'Lecture et Ecriture'
    db.session.query(UserRights).filter_by(
        document_id=document_id, user_id=user_id).update({
            'read': read, 'write': write})
    db.session.commit()
    return jsonify({'label_rights': label_rights, 'rights': rights})


@nuts.app.route('/delete_rights', methods=('POST',))
def delete_rights():
    """Remove rights for a document."""
    document_id = request.form['document_id']
    user_id = request.form['user_id']
    db.session.query(UserRights).filter_by(
        document_id=document_id, user_id=user_id).delete()
    db.session.commit()
    return user_id


@nuts.app.route('/pdf_link/<string:document_type>/<string:document_name>')
def pdf_link(document_type, document_name):
    """Return the link for PDF downloading."""
    return url_for(
        'pdf', document_type=document_type, document_name=document_name)
