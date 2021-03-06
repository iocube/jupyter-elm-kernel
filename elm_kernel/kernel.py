from collections import deque
import contextlib
import io
from ipykernel.kernelbase import Kernel
import os
import subprocess
import sys
from tempfile import TemporaryDirectory


class ElmKernel(Kernel):
    implementation = 'elm_kernel'
    implementation_version = '1.0'
    language = 'no-op'
    language_version = '0.1'
    language_info = {'name': 'elm',
                     'codemirror_mode': 'elm',
                     'mimetype': 'text/x-elm',
                     'file_extension': '.elm'}
    banner = "Display Elm output"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._code = []
        self._tempdir = TemporaryDirectory()

    def do_shutdown(self, restart):
        self._tempdir.cleanup()

    def do_execute(self, code, silent,
                   store_history=True,
                   user_expressions=None,
                   allow_stdin=False):
        self._code.append(code)

        if self._should_compile:
            try:
                code = "\n".join(self._code)
                self._code = []
                self._compile(code)
            except Exception as exc:
                self._send_error_result(str(exc))
                return {
                    'status': 'error',
                    'execution_count': self.execution_count,
                }

        return {
            'status': 'ok',
            'execution_count': self.execution_count,
            'payload': [],
            'user_expressions': {},
        }

    @contextlib.contextmanager
    def _tempfile(self, filename):
        """Yield `filename` inside the tempdir, but don't actually create the file.
        Then, on exit, delete the file if it exists.
        """
        try:
            path = os.path.join(self._tempdir.name, filename)
            yield path
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)

    def _compile(self, code):
        with self._tempfile('input.elm') as infile,\
             self._tempfile('index.js') as outfile:

            with open(infile, mode='wt') as f:
                f.write(code)

            try:
                subprocess.run(
                    ['elm-make', infile, '--yes',
                        '--output={}'.format(outfile)],
                    cwd=self._tempdir.name,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding=sys.getdefaultencoding())

                with open(outfile, mode='rt') as f:
                    javascript = f.read()

                self._send_success_result(javascript)

            except subprocess.CalledProcessError as err:
                # When compilation fails we send the compiler output to the
                # user but we don't count this as an error. A compiler error
                # might actually be the desired output of the cell.
                self._send_error_result(err.stdout)

    @property
    def _should_compile(self):
        assert self._code, "Should not be querying for compilation with no code!"
        last_line = deque(io.StringIO(self._code[-1]), 1)[0]
        return last_line == '-- compile-code'

    def _send_error_result(self, msg):
        """Send an error message to the client.

        `msg` is the message to be sent to the client.
        """
        self.send_response(
            self.iopub_socket,
            'display_data',
            {
                'metadata': {},
                'data': {
                    'text/html': '<pre>{}</pre>'.format(msg)
                }
            }
        )

    def _send_success_result(self, javascript):
        """Send messages to the client with the results of a successful compilation.

        `javascript` is the javascript generated by elm-make.
        """
        # TODO: pull module name from `code`
        module_name = "Main"

        div_id = 'elm-div-' + str(self.execution_count)

        template = """
            var defineElm = function(cb) {{
                if (this.Elm) {{
                    this.oldElm = this.Elm;
                }}
                var define = null;

                {js}

                cb();
            }}
            ;

            var obj = new Object();
            defineElm.bind(obj)(function(){{
                var mountNode = document.getElementById('{div_id}');
                obj.Elm. {module_name}.embed(mountNode);
            }});
        """

        javascript = template.format(
            js=javascript,
            module_name=module_name,
            div_id=div_id)

        self.send_response(
            self.iopub_socket,
            'display_data',
            {
                'metadata': {},
                'data': {
                    'text/html': '<div id="' + div_id + '"></div>'
                }
            }
        )

        self.send_response(
            self.iopub_socket,
            'display_data',
            {
                'metadata': {},
                'data': {
                    'application/javascript': javascript
                }
            })


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ElmKernel)
