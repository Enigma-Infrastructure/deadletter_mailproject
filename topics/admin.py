from django.contrib import admin
from .models import Topic, LetterTopic, LetterTopicVote


admin.site.register(Topic)
admin.site.register(LetterTopic)
admin.site.register(LetterTopicVote)
