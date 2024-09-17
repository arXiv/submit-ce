"""Descriptive user-firendly error explanations for process errors."""

from flask import url_for, Markup

"""Attempt to convert short error messages into  more user-friendly
warning messages.

These messages are accompanied by user instructions (what to do) that
appear in the process.html template).

NOTE: Move these into subdirectory at some point. Possibly as part of process
    package.
"""

SUCCESS_MARKUP = \
    Markup("We are processing your ui-app. This may take a minute or two." \
            " This page will refresh automatically every 5 seconds. You can " \
            " also refresh this page manually to check the current status. ")

TEX_PRODUCED_MARKUP = \
    Markup("The ui-app PDF file appears to have been produced by TeX. " \
           "<p>This file has been rejected as part your ui-app because " \
           "it appears to be pdf generated from TeX/LaTeX source. " \
           "For the reasons outlined at in the Why TeX FAQ we insist on " \
           "ui-app of the TeX source rather than the processed " \
           "version.</p><p>Our software includes an automatic TeX " \
           "processing script that will produce PDF, PostScript and " \
           "dvi from your TeX source. If our determination that your " \
           "ui-app is TeX produced is incorrect, you should send " \
           "e-mail with your ui-app ID to " \
           '<a href="mailto:help@arxiv.org">arXiv administrators.</a></p>')

DOCKER_ERROR_MARKUOP = \
    Markup("Our automatic TeX processing system has failed to launch. " \
           "There is a good cchance we are aware of the issue, but if the " \
           "problem persists you should send e-mail with your ui-app " \
           'number to <a href="mailto:help@arxiv.org">arXiv administrators.</a></p>')