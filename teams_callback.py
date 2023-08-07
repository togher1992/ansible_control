from ansible.plugins.callback import CallbackBase
from ansible.utils.display import Display
from jinja2 import Environment, BaseLoader
import requests
import os
import json

display = Display()

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'teams_callback'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)
        self.teams_webhook_url = 'http://eda.togher.com:5000'
        self.jinja2_template_path = os.path.join(os.path.dirname(__file__), '../templates/teams_message.j2')
        self.host_vars = None

    def post_to_teams(self, payload):
        display.v("Post to Teams Running")
        headers = {'Content-Type': 'application/json'}
        response = requests.post(self.teams_webhook_url, json=payload, headers=headers)
        if response.status_code != 200:
            self._display.warning('Failed to send message to Microsoft Teams')
            
    def v2_playbook_on_play_start(self, play):
        display.v("v2_playbook_on_play_start method is being called")
        self.play = play
        # get variable manager and retrieve extra-vars
        vm = play.get_variable_manager()
        self.extra_vars = vm.extra_vars
        self.play_vars = vm.get_vars(self.play)
        # The following is used to retrieve variables defined under group_vars or host_vars.
        # If the same variable is defined under both with the same scope, the one defined under host_vars takes precedence.
        self.host_vars = vm.get_vars()['hostvars']
        display.v(f"extra_vars: {self.extra_vars}")
        display.v(f"play_vars: {self.play_vars}")
        display.v(f"host_vars: {self.host_vars}")

    def v2_playbook_on_stats(self, stats):
        display.v("Playbook on Stats Function Running")
        
        j2_env = Environment(loader=BaseLoader())
        template = j2_env.from_string(open(self.jinja2_template_path).read())

        hosts = sorted(stats.processed.keys())
        for current_host in hosts:
            summary = stats.summarize(current_host)            
            try:
                rendered_template = template.render({
                    'host': current_host,
                    'hostvars': self.host_vars,
                    'task_name': 'Playbook Summary',
                    'status': 'OK' if summary['failures'] == 0 else 'FAILED'
                })
                payload = json.loads(rendered_template)
            except Exception as e:
                display.v(f"Templating error: {e}")
                return  # Exit the function, or handle the error in another way
            display.v(f"Payload: {payload}")
            self.post_to_teams(payload)
