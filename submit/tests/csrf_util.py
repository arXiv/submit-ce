import re

CSRF_PATTERN = (r'\<input id="csrf_token" name="csrf_token" type="hidden"'
                r' value="([^\"]+)">')


def parse_csrf_token(input):
    """Gets the csrf token from a WTForm. 

    This can usually be passed back to the web app as the field 'csrf_token' """
    try:
        txt = None
        if hasattr(input, 'text'):
            txt = input.text
        elif hasattr(input, 'data'):
            txt = input.data.decode('utf-8')
        else:
            txt = input


        return re.search(CSRF_PATTERN, txt).group(1)
    except AttributeError:
        raise Exception('Could not find CSRF token')
    return token
