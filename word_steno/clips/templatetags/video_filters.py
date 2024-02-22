from django import template

register = template.Library()


@register.filter(name="humanize_seconds")
def humanize_seconds(value):
    if value is None:
        return "Length not specified"

    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"
    elif minutes:
        return f"{minutes}:{str(seconds).zfill(2)}"
    else:
        return f"0:{str(seconds).zfill(2)}"
