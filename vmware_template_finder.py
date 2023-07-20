#!/usr/bin/python

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.vmware_rest_client import VmwareRestClient
import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class VMwareTemplateFinder(VmwareRestClient):
    def __init__(self, module):
        """Constructor."""
        super(VMwareTemplateFinder, self).__init__(module)
        self.hostname = self.params.get('hostname')
        self.library = self.params.get('library')
        self.os_version = self.params.get('os_version')
        self.validate_certs = self.params.get('validate_certs')
        self.username = self.params.get('username')
        self.password = self.params.get('password')
        self.port = self.params.get('port')

        # Session management
        self.session = self.get_vcenter_session()

    def api_call(self, url, method='get', headers=None, **kwargs):
        response = getattr(requests, method)(url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json() if response.text else None

    def get_vcenter_session(self):
        url = f"https://{self.hostname}/api/session"
        response = requests.post(url, auth=(self.username, self.password), verify=self.validate_certs)
        response.raise_for_status()
        return response.json()

    def get_template_attr(self, template_id, attr):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data.get(attr, '') if data else ''

    def get_library_id(self):
        url = f"https://{self.hostname}/api/content/library?action=find"
        headers = {'vmware-api-session-id': self.session}
        params = {'name': self.library, 'type': 'LOCAL'}
        data = self.api_call(url, method='post', headers=headers, json=params, verify=self.validate_certs)
        return data[0].replace('"', '') if data else None

    def get_all_template_ids(self, library_id):
        url = f"https://{self.hostname}/api/content/library/item?library_id={library_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, method='get', headers=headers, verify=self.validate_certs)
        templates = []
        if data:
            for item in data:
                if item:
                    template_id = item.replace('"', '')
                    template_name = self.get_template_attr(template_id, 'name')
                    template_notes = self.get_template_attr(template_id, 'description')
                    vm_name = template_name.split('_')[0] if '_' in template_name else template_name
                    templates.append((template_id, vm_name, template_name, template_notes))
        return templates  # Return an empty list if no templates

    def find_template(self, library_id):
        templates = self.get_all_template_ids(library_id)
        if templates:
            for template_id, _, template_name, template_notes in templates:
                if template_notes:
                    notes = json.loads(template_notes.replace("'", '"'))
                    published_status = notes.get('published', False)
                    os_version = notes.get('operatingSystemVersion', '')
                    if isinstance(published_status, str):
                        published_status = published_status not in ['False', 'Retired']
                    if published_status and os_version == self.os_version:
                        return template_name  # Return the name of the first matching template
        return None  # If no matching templates are found

    def execute(self):
        """Execute module functionality."""
        library_id = self.get_library_id()
        if not library_id:
            self.module.fail_json(msg="Library not found.")
        else:
            template_name = self.find_template(library_id)
            if template_name:
                self.module.exit_json(changed=False, template_name=template_name)
            else:
                self.module.fail_json(msg="No matching template found.")


def main():
    """Main."""
    argument_spec = {
        "hostname": {"type": "str", "required": True},
        "username": {"type": "str", "required": True},
        "password": {"type": "str", "required": True, "no_log": True},
        "validate_certs": {"type": "bool", "required": False, "default": False},
        "port": {"type": "str", "required": False, "default": "443"},
        "library": {"type": "str", "required": True},
        "os_version": {"type": "str", "required": True},
    }

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    template_finder = VMwareTemplateFinder(module)
    template_finder.execute()


if __name__ == "__main__":
    main()
