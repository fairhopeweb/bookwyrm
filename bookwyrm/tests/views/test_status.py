''' test for app action functionality '''
from unittest.mock import patch
from django.template.response import TemplateResponse
from django.test import TestCase
from django.test.client import RequestFactory

from bookwyrm import forms, models, views
from bookwyrm.activitypub import ActivitypubResponse
from bookwyrm.settings import DOMAIN


class StatusViews(TestCase):
    ''' viewing and creating statuses '''
    def setUp(self):
        ''' we need basic test data and mocks '''
        self.factory = RequestFactory()
        self.local_user = models.User.objects.create_user(
            'mouse@local.com', 'mouse@mouse.com', 'mouseword',
            local=True, localname='mouse',
            remote_id='https://example.com/users/mouse',
        )
        with patch('bookwyrm.models.user.set_remote_server'):
            self.remote_user = models.User.objects.create_user(
                'rat', 'rat@email.com', 'ratword',
                local=False,
                remote_id='https://example.com/users/rat',
                inbox='https://example.com/users/rat/inbox',
                outbox='https://example.com/users/rat/outbox',
            )

        work = models.Work.objects.create(title='Test Work')
        self.book = models.Edition.objects.create(
            title='Example Edition',
            remote_id='https://example.com/book/1',
            parent_work=work
        )


    def test_status_page(self):
        ''' there are so many views, this just makes sure it LOADS '''
        view = views.Status.as_view()
        status = models.Status.objects.create(
            content='hi', user=self.local_user)
        request = self.factory.get('')
        request.user = self.local_user
        with patch('bookwyrm.views.status.is_api_request') as is_api:
            is_api.return_value = False
            result = view(request, 'mouse', status.id)
        self.assertIsInstance(result, TemplateResponse)
        self.assertEqual(result.template_name, 'status.html')
        self.assertEqual(result.status_code, 200)

        with patch('bookwyrm.views.status.is_api_request') as is_api:
            is_api.return_value = True
            result = view(request, 'mouse', status.id)
        self.assertIsInstance(result, ActivitypubResponse)
        self.assertEqual(result.status_code, 200)


    def test_replies_page(self):
        ''' there are so many views, this just makes sure it LOADS '''
        view = views.Replies.as_view()
        status = models.Status.objects.create(
            content='hi', user=self.local_user)
        request = self.factory.get('')
        request.user = self.local_user
        with patch('bookwyrm.views.status.is_api_request') as is_api:
            is_api.return_value = False
            result = view(request, 'mouse', status.id)
        self.assertIsInstance(result, TemplateResponse)
        self.assertEqual(result.template_name, 'status.html')
        self.assertEqual(result.status_code, 200)

        with patch('bookwyrm.views.status.is_api_request') as is_api:
            is_api.return_value = True
            result = view(request, 'mouse', status.id)
        self.assertIsInstance(result, ActivitypubResponse)
        self.assertEqual(result.status_code, 200)


    def test_handle_status(self):
        ''' create a status '''
        view = views.CreateStatus.as_view()
        form = forms.CommentForm({
            'content': 'hi',
            'user': self.local_user.id,
            'book': self.book.id,
            'privacy': 'public',
        })
        request = self.factory.post('', form.data)
        request.user = self.local_user
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, 'comment')
        status = models.Comment.objects.get()
        self.assertEqual(status.content, '<p>hi</p>')
        self.assertEqual(status.user, self.local_user)
        self.assertEqual(status.book, self.book)

    def test_handle_status_reply(self):
        ''' create a status in reply to an existing status '''
        view = views.CreateStatus.as_view()
        user = models.User.objects.create_user(
            'rat', 'rat@rat.com', 'password', local=True)
        parent = models.Status.objects.create(
            content='parent status', user=self.local_user)
        form = forms.ReplyForm({
            'content': 'hi',
            'user': user.id,
            'reply_parent': parent.id,
            'privacy': 'public',
        })
        request = self.factory.post('', form.data)
        request.user = user
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, 'reply')
        status = models.Status.objects.get(user=user)
        self.assertEqual(status.content, '<p>hi</p>')
        self.assertEqual(status.user, user)
        self.assertEqual(
            models.Notification.objects.get().user, self.local_user)

    def test_handle_status_mentions(self):
        ''' @mention a user in a post '''
        view = views.CreateStatus.as_view()
        user = models.User.objects.create_user(
            'rat@%s' % DOMAIN, 'rat@rat.com', 'password',
            local=True, localname='rat')
        form = forms.CommentForm({
            'content': 'hi @rat',
            'user': self.local_user.id,
            'book': self.book.id,
            'privacy': 'public',
        })
        request = self.factory.post('', form.data)
        request.user = self.local_user

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, 'comment')
        status = models.Status.objects.get()
        self.assertEqual(list(status.mention_users.all()), [user])
        self.assertEqual(models.Notification.objects.get().user, user)
        self.assertEqual(
            status.content,
            '<p>hi <a href="%s">@rat</a></p>' % user.remote_id)

    def test_handle_status_reply_with_mentions(self):
        ''' reply to a post with an @mention'ed user '''
        view = views.CreateStatus.as_view()
        user = models.User.objects.create_user(
            'rat', 'rat@rat.com', 'password',
            local=True, localname='rat')
        form = forms.CommentForm({
            'content': 'hi @rat@example.com',
            'user': self.local_user.id,
            'book': self.book.id,
            'privacy': 'public',
        })
        request = self.factory.post('', form.data)
        request.user = self.local_user

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, 'comment')
        status = models.Status.objects.get()

        form = forms.ReplyForm({
            'content': 'right',
            'user': user.id,
            'privacy': 'public',
            'reply_parent': status.id
        })
        request = self.factory.post('', form.data)
        request.user = user
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, 'reply')

        reply = models.Status.replies(status).first()
        self.assertEqual(reply.content, '<p>right</p>')
        self.assertEqual(reply.user, user)
        # the mentioned user in the parent post is only included if @'ed
        self.assertFalse(self.remote_user in reply.mention_users.all())
        self.assertTrue(self.local_user in reply.mention_users.all())

    def test_find_mentions(self):
        ''' detect and look up @ mentions of users '''
        user = models.User.objects.create_user(
            'nutria@%s' % DOMAIN, 'nutria@nutria.com', 'password',
            local=True, localname='nutria')
        self.assertEqual(user.username, 'nutria@%s' % DOMAIN)

        self.assertEqual(
            list(views.status.find_mentions('@nutria'))[0],
            ('@nutria', user)
        )
        self.assertEqual(
            list(views.status.find_mentions('leading text @nutria'))[0],
            ('@nutria', user)
        )
        self.assertEqual(
            list(views.status.find_mentions(
                'leading @nutria trailing text'))[0],
            ('@nutria', user)
        )
        self.assertEqual(
            list(views.status.find_mentions(
                '@rat@example.com'))[0],
            ('@rat@example.com', self.remote_user)
        )

        multiple = list(views.status.find_mentions(
            '@nutria and @rat@example.com'))
        self.assertEqual(multiple[0], ('@nutria', user))
        self.assertEqual(multiple[1], ('@rat@example.com', self.remote_user))

        with patch('bookwyrm.views.status.handle_remote_webfinger') as rw:
            rw.return_value = self.local_user
            self.assertEqual(
                list(views.status.find_mentions('@beep@beep.com'))[0],
                ('@beep@beep.com', self.local_user)
            )
        with patch('bookwyrm.views.status.handle_remote_webfinger') as rw:
            rw.return_value = None
            self.assertEqual(list(views.status.find_mentions(
                '@beep@beep.com')), [])

        self.assertEqual(
            list(views.status.find_mentions('@nutria@%s' % DOMAIN))[0],
            ('@nutria@%s' % DOMAIN, user)
        )

    def test_format_links(self):
        ''' find and format urls into a tags '''
        url = 'http://www.fish.com/'
        self.assertEqual(
            views.status.format_links(url),
            '<a href="%s">www.fish.com/</a>' % url)
        self.assertEqual(
            views.status.format_links('(%s)' % url),
            '(<a href="%s">www.fish.com/</a>)' % url)
        url = 'https://archive.org/details/dli.granth.72113/page/n25/mode/2up'
        self.assertEqual(
            views.status.format_links(url),
            '<a href="%s">' \
                'archive.org/details/dli.granth.72113/page/n25/mode/2up</a>' \
                % url)
        url = 'https://openlibrary.org/search' \
               '?q=arkady+strugatsky&mode=everything'
        self.assertEqual(
            views.status.format_links(url),
            '<a href="%s">openlibrary.org/search' \
                '?q=arkady+strugatsky&mode=everything</a>' % url)


    def test_to_markdown(self):
        ''' this is mostly handled in other places, but nonetheless '''
        text = '_hi_ and http://fish.com is <marquee>rad</marquee>'
        result = views.status.to_markdown(text)
        self.assertEqual(
            result,
            '<p><em>hi</em> and <a href="http://fish.com">fish.com</a> ' \
                    'is rad</p>')


    def test_handle_delete_status(self):
        ''' marks a status as deleted '''
        view = views.DeleteStatus.as_view()
        status = models.Status.objects.create(
            user=self.local_user, content='hi')
        self.assertFalse(status.deleted)
        request = self.factory.post('')
        request.user = self.local_user
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
        status.refresh_from_db()
        self.assertTrue(status.deleted)
