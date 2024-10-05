"""Test abstract cleanup"""

from .. import SetAbstract
from arxiv.base.filters import abstract_lf_to_br

from ... import Agent


def test_paragraph_cleanup():
    agent = Agent(native_id="fakeid",
                  name="bob",
                  username="bob",
                  email="<EMAIL>",
                  )
    awlb = "Paragraph 1.\n  \nThis should be paragraph 2"
    assert '<br' in abstract_lf_to_br(awlb) # sanity check: abstract filter does put <br> in

    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in  abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n\t\nThis should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace (tab)

    awlb = "Paragraph 1.\n  \nThis should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n \t \nThis should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n     \nThis should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n This should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n\tThis should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace

    awlb = "Paragraph 1.\n  This should be p 2."
    e = SetAbstract(creator=agent, abstract=awlb)
    assert '<br' in abstract_lf_to_br(e.abstract) # cleanup must preserve <br> creating whitespace
