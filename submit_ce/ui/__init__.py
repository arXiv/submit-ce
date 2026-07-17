import re

from arxiv.auth.domain import Session
from markupsafe import Markup


SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org">arXiv support</a>.'
)

def get_device_type(user_agent):
    """
    Parses a user agent string to determine the device type.

    Parameters:
        user_agent: The user agent string from the HTTP request headers.

    Returns:
        A string indicating the device type: "Mobile", "Tablet", "Computer" or the first
        20 chars of the user_agent.
    """
    if not user_agent:
        return "ua-not-set"

    crawler_regex = re.compile(r'.*(https?://[^\s)]+).*', re.IGNORECASE)
    mobile_regex = re.compile(r".*(Mobi|iPh(one|od)|IEMobile|BlackBerry|Android.*Mobile|Opera Mini|windows phone).*", re.IGNORECASE)
    # this might catch some settop boxes
    tablet_regex = re.compile(r".*(Tablet|iPad|Android(?!.*Mobile)).*", re.IGNORECASE)
    computer_regex = re.compile(r".*(Windows NT|Macintosh|X11|Linux(?!.*Mobile|.*Android)).*", re.IGNORECASE)

    crawler_match = crawler_regex.match(user_agent)
    if crawler_match:
        return crawler_match.group(1)
    if mobile_regex.match(user_agent):
        return "Mobile"
    elif tablet_regex.match(user_agent):
        return "Tablet"
    elif computer_regex.match(user_agent):
        return "Computer"
    else:
        return user_agent[:25]


# Bits of the "classic" capability code produced by
# arxiv.auth.legacy.util.compute_capabilities:
#   flag_edit_users   -> 2  (admin)
#   flag_email_verified -> 4
#   flag_edit_system  -> 8  (system/"god", i.e. dev)
# TODO move these to somewhere under arxiv.auth.auth
ADMIN_MASK = 1 << 1
DEV_MASK = 1 << 3

def is_admin(session: Session)->bool:
    return bool(getattr(session.authorizations, "classic", 0) & ADMIN_MASK)


def is_dev(session: Session)->bool:
    return bool(getattr(session.authorizations, "classic", 0) & DEV_MASK)
