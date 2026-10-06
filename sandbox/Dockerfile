# Code-sandbox runner image. The runner is stdlib-only, so there is nothing to install.
# Built into its own image so the sandbox no longer depends on which branch is checked out
# in the folder compose runs from (it used to bind-mount runner.py from there).
FROM python:3.11-slim
COPY runner.py /runner.py
CMD ["python", "-u", "/runner.py"]
