"""Tests for tex autotex log filters."""

from unittest import TestCase
import re

from submit.filters import compilation_log_display

class Test_TeX_Autotex_Log_Markup(TestCase):
    """
    Test compilation_log_display routine directly.

    In these tests I will pass in strings and compare the marked up
    response to what we are expecting.

    """

    def test_general_markup_filters(self) -> None:
        """
        Test basic markup filters.

        These filters do not limit application to specific TeX runs.

        """
        def contains_markup(marked_up_string: str, expected_markup: str) -> bool:
            """
            Check whether desired markup is contained in the resulting string.

            Parameters
            ----------
            marked_up_string : str
                String returned from markup routine.

            expected_markup : str
                Highlighed snippet we expect to find in the returned string.

            Returns
            -------
            True when we fild the expected markup, False otherwise.

            """
            if re.search(expected_markup, marked_up_string,
                         re.IGNORECASE | re.MULTILINE):
                return True

            return False

        # Dummy arguments
        test_id = '1234567'
        test_status = 'succeeded'

        # Informational TeX run marker
        input_string = ("[verbose]: ~~~~~~~~~~~ Running pdflatex for the "
                        "second time ~~~~~~~~")

        marked_up = compilation_log_display(input_string, test_id, test_status)

        expected_string = (r'\[verbose]: <span class="tex-info">~~~~~~~~~~~ '
                           r'Running pdflatex for the second time ~~~~~~~~'
                           r'<\/span>')

        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Looking for informational TeX run markup.")

        # Successful event markup
        input_string = ("[verbose]: Extracting files from archive: 5.tar")

        marked_up = compilation_log_display(input_string, test_id, test_status)

        expected_string = (r'\[verbose]: <span class="tex-success">Extracting '
                           r'files from archive:<\/span> 5.tar')

        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Looking for successful event markup.")

        # Citation Warning
        input_string = ("LaTeX Warning: Citation `GH' on page 1320 undefined "
                        "on input line 214.")

        marked_up = compilation_log_display(input_string, test_id, test_status)

        expected_string = (r'LaTeX Warning: <span class="tex-warning">'
                           r'Citation `GH&#x27; on page 1320 undefined<\/span> on'
                           r' input line 214\.')

        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Looking for Citation warning.")

        # Danger
        input_string = ("! Emergency stop.")

        marked_up = compilation_log_display(input_string, test_id, test_status)

        expected_string = (r'! <span class="tex-danger">Emergency stop<\/span>\.')

        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Looking for danger markup.")

        # Fatal
        input_string = ("[verbose]: Fatal error \n[verbose]: tex 'main.tex' failed.")

        marked_up = compilation_log_display(input_string, test_id, test_status)

        expected_string = (r'\[verbose]: <span class="tex-fatal">Fatal<\/span> error')

        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Looking for fatal markup.")

        # contains HTML markup - from smileyface.svg
        input_string = """
            <?xml version="1.0" encoding="UTF-8" standalone="no"?>
                <svg width="174px" height="173px" version="1.1">
                    <title>Smileybones</title>
                    <desc>Created with Sketch.</desc>
                    <defs></defs>
                    <g id="Smileybones" stroke="none" stroke-width="1">
                    </g>
                </svg>"""

        expected_string = """&lt;?xml version=&quot;1.0&quot; encoding=&quot;UTF-8&quot; standalone=&quot;no&quot;?&gt;
                &lt;svg width=&quot;174px&quot; height=&quot;173px&quot; version=&quot;1.1&quot;&gt;
                    &lt;title&gt;Smileybones&lt;/title&gt;
                    &lt;desc&gt;Created with Sketch.&lt;/desc&gt;
                    &lt;defs&gt;&lt;/defs&gt;
                    &lt;g id=&quot;Smileybones&quot; stroke=&quot;none&quot; stroke-width=&quot;1&quot;&gt;
                    &lt;/g&gt;
                &lt;/svg&gt;"""

        expected_string = """&lt;title&gt;Smileybones&lt;/title&gt;
                    &lt;desc&gt;Created with Sketch.&lt;/desc&gt;
                    &lt;defs&gt;&lt;/defs&gt;
                    &lt;g id=&quot;Smileybones&quot; stroke=&quot;none&quot; stroke-width=&quot;1&quot;&gt;
                    &lt;/g&gt;"""

        marked_up = compilation_log_display(input_string, test_id, test_status)
        
        found = contains_markup(marked_up, expected_string)

        self.assertTrue(found, "Checking that XML/HTML markup is escaped properly.")