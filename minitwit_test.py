# -*- coding: utf-8 -*-
import os
import unittest

import minitwit

DATABASE = "./tmp/minitwit_test.db"
class MiniTwitTestCase(unittest.TestCase):
    def setUp(self):
        """Before each test, set up a blank database"""
        # Ensure the test directory exists
        if not os.path.exists("./tmp"):
            os.makedirs("./tmp")

        # Set the correct database path BEFORE initializing
        minitwit.app.config["TESTING"] = True
        minitwit.app.config["DATABASE"] = DATABASE

        # Initialize database
        minitwit.init_db()
        
        self.app = minitwit.app.test_client()

    def tearDown(self):
        """Get rid of the database again after each test."""
        os.remove(DATABASE)

    # helper functions

    def register(self, username, password, password2=None, email=None):
        """Helper function to register a user"""
        if password2 is None:
            password2 = password
        if email is None:
            email = username + '@example.com'
        return self.app.post('/api/register', data={
            'username':     username,
            'password':     password,
            'password2':    password2,
            'email':        email
        }, follow_redirects=True)

    def login(self, username, password):
        """Helper function to login"""
        return self.app.post('/api/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)

    def register_and_login(self, username, password):
        """Registers and logs in in one go"""
        self.register(username, password)
        return self.login(username, password)

    def logout(self):
        """Helper function to logout"""
        return self.app.get('/api/logout', follow_redirects=True)

    def add_message(self, text):
        """Records a message"""
        rv = self.app.post('/api/add_message', data={'text': text},
                           follow_redirects=True)
        if text:
            assert 'Your message was recorded' == rv.get_json()["message"]
        return rv

    # testing functions
    def test_register(self):
        """Make sure registering works with the API endpoint"""

        rv = self.app.post('/api/register', data={
            'username': 'user1',
            'password': 'default',
            'password2': 'default',
            'email': 'user1@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 201


        assert b'You were successfully registered and can login now' in rv.data

        rv = self.app.post('/api/register', data={
            'username': 'user1',
            'password': 'default',
            'password2': 'default',
            'email': 'user1@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 400
        assert 'The username is already taken' == rv.get_json()["error"]

        rv = self.app.post('/api/register', data={
            'username': '',
            'password': 'default',
            'password2': 'default',
            'email': 'empty@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 400
        assert 'You have to enter a username' == rv.get_json()["error"]

        rv = self.app.post('/api/register', data={
            'username': 'meh',
            'password': '',
            'password2': '',
            'email': 'meh@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 400
        assert 'You have to enter a password' == rv.get_json()["error"]

        rv = self.app.post('/api/register', data={
            'username': 'meh',
            'password': 'x',
            'password2': 'y',
            'email': 'meh@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 400
        assert 'The two passwords do not match' == rv.get_json()["error"]

        rv = self.app.post('/api/register', data={
            'username': 'meh',
            'password': 'foo',
            'password2': 'foo',
            'email': 'broken'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 400
        assert 'You have to enter a valid email address' == rv.get_json()["error"]

    def test_login_logout(self):
        """Make sure logging in and logging out works with the API endpoint"""
        rv = self.app.post('/api/register', data={
            'username': 'user1',
            'password': 'default',
            'password2': 'default',
            'email': 'user1@example.com'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 201

        rv = self.app.post('/api/login', data={
            'username': 'user1',
            'password': 'default'
        }, content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 200
        assert 'You were logged in' == rv.get_json()["message"]

        rv = self.app.get('/api/logout')
        assert rv.status_code == 200
        assert 'You were logged out' == rv.get_json()["message"]

        rv = self.app.post('/api/login', data={
            'username': 'user1',
            'password': 'wrongpassword'
        }, content_type="application/x-www-form-urlencoded")

        assert rv.status_code == 401
        assert 'Invalid password' == rv.get_json()["error"]

        rv = self.app.post('/api/login', data={
            'username': 'user2',
            'password': 'wrongpassword'
        }, content_type="application/x-www-form-urlencoded")

        assert rv.status_code == 401
        assert 'Invalid username' == rv.get_json()["error"]

    def test_message_recording(self):
        """Check if adding messages works"""
        self.register_and_login('foo', 'default')
        self.add_message('test message 1')
        self.add_message('<test message 2>')
        rv = self.app.get('/')
        assert b'test message 1' in rv.data
        assert b'&lt;test message 2&gt;' in rv.data

    def test_timelines(self):
        """Make sure that timelines work"""
        self.register_and_login('foo', 'default')
        self.add_message('the message by foo')
        self.logout()
        self.register_and_login('bar', 'default')
        self.add_message('the message by bar')
        rv = self.app.get('/public')
        assert b'the message by foo' in rv.data
        assert b'the message by bar' in rv.data

        # bar's timeline should just show bar's message
        rv = self.app.get('/')
        assert b'the message by foo' not in rv.data
        assert b'the message by bar' in rv.data

        # now let's follow foo
        rv = self.app.get('api/foo/follow', follow_redirects=True)
        assert 'You are now following foo' == rv.get_json()["message"]
        # we should now see foo's message
        rv = self.app.get('/')
        assert b'the message by foo' in rv.data
        assert b'the message by bar' in rv.data

        # but on the user's page we only want the user's message
        rv = self.app.get('/bar')
        assert b'the message by foo' not in rv.data
        assert b'the message by bar' in rv.data
        rv = self.app.get('/foo')
        assert b'the message by foo' in rv.data
        assert b'the message by bar' not in rv.data

        # now unfollow and check if that worked
        rv = self.app.get('/foo/unfollow', follow_redirects=True)
        assert b'You are no longer following &#34;foo&#34;' in rv.data
        rv = self.app.get('/')
        assert b'the message by foo' not in rv.data
        assert b'the message by bar' in rv.data


if __name__ == '__main__':
    unittest.main()
