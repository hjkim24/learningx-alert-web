from django.conf import settings
from django.db import models


class CanvasConnection(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="canvas_connection",
    )
    canvas_user_id = models.CharField(max_length=128)
    canvas_name = models.CharField(max_length=255)
    encrypted_token = models.TextField()
    verified_at = models.DateTimeField()

    def __str__(self):
        return f"Canvas connection for user {self.user_id}"
