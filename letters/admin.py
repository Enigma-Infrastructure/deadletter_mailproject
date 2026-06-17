from django.contrib import admin
from .models import LetterInstance, LetterHop


class LetterHopInline(admin.TabularInline):
    model  = LetterHop
    extra  = 0
    fields = ('status', 'city', 'venue_hint', 'notes', 'created_at', 'updated_by')
    readonly_fields = ('created_at',)


@admin.register(LetterInstance)
class LetterInstanceAdmin(admin.ModelAdmin):
    list_display  = ('code', 'request', 'is_public', 'created_at')
    list_filter   = ('is_public',)
    search_fields = ('code', 'request__nickname', 'body_text')
    readonly_fields = ('code', 'created_at')
    inlines = [LetterHopInline]
    fieldsets = (
        ('Letter', {
            'fields': ('code', 'request', 'body_text'),
        }),
        ('Visibility', {
            'fields': ('is_public', 'written_by'),
        }),
        ('Meta', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )


@admin.register(LetterHop)
class LetterHopAdmin(admin.ModelAdmin):
    list_display  = ('letter', 'status', 'city', 'venue_hint', 'created_at', 'updated_by')
    list_filter   = ('status', 'city')
    search_fields = ('letter__code', 'city', 'venue_hint', 'notes')
    readonly_fields = ('created_at',)
