FROM python:3.11 AS builder

WORKDIR /usr/app

RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

RUN pip install --upgrade pip

COPY . .
RUN pip install --no-cache-dir .


#FROM python:3.7 AS test_runner
#WORKDIR /tmp
#COPY --from=builder /venv /venv
#COPY --from=builder /usr/app/tests tests
#ENV PATH=/venv/bin:$PATH
#
## install test dependencies
#RUN pip install pytest
#
## run tests
#RUN pytest tests


FROM python:3.11 AS service
WORKDIR /root/app/site-packages
COPY --from=builder /venv /venv
ENV PATH=/venv/bin:$PATH
