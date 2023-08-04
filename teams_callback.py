from ansible.plugins.callback import CallbackBase
from ansible.template import Templar
import requests
import os
import json

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'teams_callback'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)
        self.teams_webhook_url = os.getenv('TEAMS_WEBHOOK_URL')
        self.jinja2_template_path = os.path.join(os.path.dirname(__file__), 'teams_message.j2')

    def post_to_teams(self, payload):
        headers = {'Content-Type': 'application/json'}
        response = requests.post(self.teams_webhook_url, json=payload, headers=headers)
        if response.status_code != 200:
            self._display.warning('Failed to send message to Microsoft Teams')

    def v2_playbook_on_stats(self, stats):
        templar = Templar(loader=self._loader)
        template_data = open(self.jinja2_template_path).read()

        hosts = sorted(stats.processed.keys())
        for host in hosts:
            summary = stats.summarize(host)
            payload = templar.template(template_data, {
                'host': host,
                'task_name': 'Playbook Summary',
                'status': 'OK' if summary['failures'] == 0 else 'FAILED'
            })
            self.post_to_teams(json.loads(payload))
