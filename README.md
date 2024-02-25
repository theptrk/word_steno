# Word Steno

Behold My Awesome Project!

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Settings

Moved to [settings](http://cookiecutter-django.readthedocs.io/en/latest/settings.html).

## Basic Commands

### Setting Up Your Users

- To create a **normal user account**, just go to Sign Up and fill out the form. Once you submit it, you'll see a "Verify Your E-mail Address" page. Go to your console to see a simulated email verification message. Copy the link into your browser. Now the user's email should be verified and ready to go.

- To create a **superuser account**, use this command:

      $ python manage.py createsuperuser

For convenience, you can keep your normal user logged in on Chrome and your superuser logged in on Firefox (or similar), so that you can see how the site behaves for both kinds of users.

### Type checks

Running type checks with mypy:

    $ mypy word_steno

### Test coverage

To run the tests, check your test coverage, and generate an HTML coverage report:

    $ coverage run -m pytest
    $ coverage html
    $ open htmlcov/index.html

#### Running tests with pytest

    $ pytest

### Live reloading and Sass CSS compilation

Moved to [Live reloading and SASS compilation](https://cookiecutter-django.readthedocs.io/en/latest/developing-locally.html#sass-compilation-live-reloading).

## Development

### Environment Variables

You need to have `DJANGO_READ_DOT_ENV_FILE=True` in your machine and all the variables in .env will be read.

Also make sure that you have this keys in your .env

```
DEEPGRAM_API_KEY=
DATABASE_URL=
DJANGO_AWS_ACCESS_KEY_ID=
DJANGO_AWS_SECRET_ACCESS_KEY=
DJANGO_AWS_STORAGE_BUCKET_NAME=
DJANGO_AWS_S3_REGION_NAME=
```

### Start Server

To start the server you just need to run

```
python manage.py runserver
```

### Start Django Tailwind in development mode

To start Django Tailwind in development mode, run the following command in a terminal:

```
python manage.py tailwind install
python manage.py tailwind start
```

This will start a long-running process that watches files for changes. Use a combination of CTRL + C to terminate the process.

Several things are happening behind the scenes at that moment:

1. The stylesheet is updated every time you add or remove a CSS class in a Django template.
2. The django-browser-reload watches for changes in HTML and CSS files. When a Django template or CSS is updated, browser refreshes them. That gives you a smooth development experience without the need to reload the page to see updates.

## Deployment

The following details how to deploy this application.

### Tailwind theme build

To create a production build of your theme, run:

```
python manage.py tailwind build
```

This will replace the development build with a bundle optimized for production. No further actions are necessary; you can deploy!
