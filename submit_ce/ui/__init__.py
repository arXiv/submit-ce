import re

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
