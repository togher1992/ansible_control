import json
import requests
import urllib3
from ansible.module_utils.basic import *
from ansible.module_utils.vmware_rest_client import VmwareRestClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class VMwareContentLibraryManager(VmwareRestClient):
    def __init__(self, module):
        """Constructor."""
        super(VMwareContentLibraryManager, self).__init__(module)
        self.hostname = self.params.get('hostname')
        self.content_library = self.params.get('content_library')
        self.validate_certs = self.params.get('validate_certs')
        self.username = self.params.get('username')
        self.password = self.params.get('password')
        self.port = self.params.get('port')

        # Session management
        self.session = self.get_vcenter_session()

    def get_vcenter_session(self):
        url = f"https://{self.hostname}/api/session"
        response = requests.post(url, auth=(self.username, self.password), verify=self.validate_certs)
        response.raise_for_status()
        return response.json()
        
    def get_template_name(self, template_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data.get('name', '') if data else ''
        
    def get_all_template_ids(self, lib_id):
        url = f"https://{self.hostname}/api/content/library/item?library_id={lib_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, method='get', headers=headers, verify=self.validate_certs)
        if data:
            templates = []
            for item in data:
                if item:
                    template_id = item.replace('"', '')
                    template_name = self.get_template_name(template_id)
                    template_notes = self.get_template_notes(template_id)
                    vm_name = template_name.split('_')[0] if '_' in template_name else template_name
                    templates.append((template_id, vm_name, template_name, template_notes))
            return templates
        else:
            return None

    def get_template_notes(self, template_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data.get('description', '') if data else ''

    def check_content_library_state(self):
        lib_id = self.get_lib_id()
        return 'present' if lib_id else 'absent'

    def api_call(self, url, method='get', headers=None, **kwargs):
        response = getattr(requests, method)(url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json() if response.text else None

    def get_lib_id(self):
        url = f"https://{self.hostname}/api/content/library?action=find"
        headers = {'vmware-api-session-id': self.session}
        params = {'name': self.content_library, 'type': 'LOCAL'}
        data = self.api_call(url, method='post', headers=headers, json=params, verify=self.validate_certs)
        return data[0].replace('"','') if data else None

    def update_templates_in_library(self, lib_id):
        template_data = self.get_all_template_ids(lib_id)
        templates_to_update = []  # To store templates that need to be updated
        os_versions_count_false = {}  # To track the count of templates with 'published' False for each operatingSystemVersion

        # First loop through and find templates with 'published': 'False' for each operatingSystemVersion
        if template_data:
            for template_id, _, _, template_notes in template_data:
                if template_notes:
                    notes = json.loads(template_notes.replace("'", '"'))
                    os_version = notes.get('operatingSystemVersion')
                    if os_version and notes.get('published') == 'False':
                        os_versions_count_false[os_version] = os_versions_count_false.get(os_version, 0) + 1
                        notes['published'] = 'True'
                        templates_to_update.append((template_id, notes))

            # Now loop through and retire templates with 'published': 'True' only if there's a corresponding 'False'
            for template_id, _, _, template_notes in template_data:
                if template_notes:
                    notes = json.loads(template_notes.replace("'", '"'))
                    os_version = notes.get('operatingSystemVersion')
                    if os_version and notes.get('published') == 'True' and os_versions_count_false.get(os_version):
                        notes['published'] = 'Retired'
                        templates_to_update.append((template_id, notes))

        return templates_to_update

    def update_template_notes_with_id(self, template_id, notes):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        payload = {'description': f'{notes}'}
        response = requests.patch(url, headers=headers, json=payload, verify=self.validate_certs)
        if response.status_code != 204:
            self.module.fail_json(msg=f"Failed to update published status of template with ID: {template_id}")

    def process_state(self):
        if self.check_content_library_state() == 'absent':
            self.module.fail_json(msg=f"Content Library '{self.content_library}' does not exist.")
        # Get library id
        lib_id = self.get_lib_id()
        # Get all templates to update
        templates_to_update = self.update_templates_in_library(lib_id)
        # Update each template
        for template_id, notes in templates_to_update:
            self.update_template_notes_with_id(template_id, json.dumps(notes)) # Make sure to pass JSON string
        return

def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            content_library=dict(type='str', required=True),
            validate_certs=dict(type='bool', default=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port=dict(type='int', default=443)
        ),
    )

    vmware_content_library_template_manager = VMwareContentLibraryManager(module)
    vmware_content_library_template_manager.process_state()
    module.exit_json(changed=True)

if __name__ == '__main__':
    main()
