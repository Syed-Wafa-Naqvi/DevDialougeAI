from django.test import TestCase, Client
from django.contrib.auth.models import User
from chat.models import Session, GeneratedCode
from exporter.archiver import ZipArchiver

class ExporterTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='exporteruser', email='exporter@example.com', password='Password123!')
        self.user.profile.is_verified = True
        self.user.profile.save()
        self.session = Session.objects.create(user=self.user, title="Test App")
        GeneratedCode.objects.create(session=self.session, module_name="models.py", code_content="# Test models")

    def test_zip_archiver(self):
        zip_bytes = ZipArchiver.create_project_zip(self.session)
        self.assertTrue(len(zip_bytes) > 0)

    def test_download_zip_api(self):
        client = Client()
        client.login(username='exporteruser', password='Password123!')
        response = client.get(f'/api/session/{self.session.id}/download/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
