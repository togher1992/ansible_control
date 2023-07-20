#!/usr/bin/python

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.vmware_rest_client import VmwareRestClient
import requests
import json
import time
from collections import defaultdict
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class VMwareContentLibraryManager(VmwareRestClient):
    def __init__(self, module):
        """Constructor."""
        super(VMwareContentLibraryManager, self).__init__(module)
        self.hostname = self.params.get('hostname')
        self.source_library = self.params.get('source_library')
        self.destination_library = self.params.get('destination_library')
        self.validate_certs = self.params.get('validate_certs')
        self.username = self.params.get('username')
        self.password = self.params.get('password')
        self.port = self.params.get('port')

        # Session management
        self.session = self.get_vcenter_session()

        # Variables to manage template prefix count
        self.source_prefix_count = defaultdict(int)
        self.destination_prefix_count = defaultdict(int)

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

    def get_source_library_id(self):
        url = f"https://{self.hostname}/api/content/library?action=find"
        headers = {'vmware-api-session-id': self.session}
        params = {'name': self.source_library, 'type': 'LOCAL'}
        data = self.api_call(url, method='post', headers=headers, json=params, verify=self.validate_certs)
        return data[0].replace('"', '') if data else None

    def get_destination_library_id(self):
        url = f"https://{self.hostname}/api/content/library?action=find"
        headers = {'vmware-api-session-id': self.session}
        params = {'name': self.destination_library, 'type': 'LOCAL'}
        data = self.api_call(url, method='post', headers=headers, json=params, verify=self.validate_certs)
        return data[0].replace('"', '') if data else None

    def check_content_library_state(self, library_id):
        return 'present' if library_id else 'absent'

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

    def remove_unpublished_templates(self, library_id):
        templates = self.get_all_template_ids(library_id)
        for template_id, _, _, template_notes in templates:
            if not self.check_template_published(template_notes):
                self.delete_template_from_library(template_id, library_id)

    def copy_templates_to_library(self, source_library_id, destination_library_id):
        source_templates = self.get_all_template_ids(source_library_id)
        destination_templates = self.get_all_template_ids(destination_library_id)

        # Update the prefix count for source and destination libraries
        for _, vm_prefix, _, _ in source_templates:
            self.source_prefix_count[vm_prefix] += 1
        for _, vm_prefix, _, _ in destination_templates:
            self.destination_prefix_count[vm_prefix] += 1

        if source_templates:
            for template_id, vm_prefix, template_name, template_notes in source_templates:
                if self.check_template_published(template_notes):
                    # Check the number of templates with the same prefix in the destination library
                    if self.destination_prefix_count[vm_prefix] < 2:
                        if not any(d_template_name == template_name for _, _, d_template_name, _ in destination_templates):
                            self.copy_template_to_library(template_id, template_name, destination_library_id)

        self.delete_excess_templates(destination_library_id)

    def check_template_published(self, template_notes):
        if template_notes:
            notes = json.loads(template_notes.replace("'", '"'))
            published_status = notes.get('published', False)
            if isinstance(published_status, str):
                return published_status not in ['False', 'Retired']
            return published_status
        return False

    def check_template_exists(self, template_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        data = self.api_call(url, method='get', headers=headers, verify=self.validate_certs)
        return bool(data)

    def copy_template_to_library(self, template_id, template_name, destination_library_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}?action=copy"
        headers = {
            'vmware-api-session-id': self.session,
            'Content-Type': 'application/json'
        }

        # Fetch the annotations from the source template
        annotations = self.get_template_attr(template_id, 'description')
        if annotations:
            notes = json.loads(annotations.replace("'", '"'))
            notes['published'] = 'False'
        else:
            notes = {'published': 'False'}

        payload = {
            "name": template_name,
            "library_id": destination_library_id,
            "description": json.dumps(notes)  # Add the modified annotations to the destination template
        }

        response = requests.post(url, headers=headers, json=payload, verify=self.validate_certs)
        response_text = response.text
        if not response_text:
            self.module.fail_json(msg="Template copy failed.")
        else:
            return response_text

    def delete_excess_templates(self, destination_library_id):
        destination_templates = self.get_all_template_ids(destination_library_id)

        # Deleting excess templates
        for template_id, vm_prefix, _, template_notes in destination_templates:
            if self.destination_prefix_count[vm_prefix] > 2 and not self.check_template_published(template_notes):
                self.delete_template_from_library(template_id, destination_library_id)
                self.destination_prefix_count[vm_prefix] -= 1
                self.module.fail_json(msg=f"Got to end of delete excess templates bit")

    def delete_template_from_library(self, template_id, library_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        response = requests.delete(url, headers=headers, verify=self.validate_certs)
        if response.status_code != 204:
            self.module.fail_json(msg=f"Deleting template from library failed.")

    def manage_content_libraries(self):
        source_library_id = self.get_source_library_id()
        destination_library_id = self.get_destination_library_id()
        if not source_library_id or not destination_library_id:
            self.module.fail_json(msg="Either source or destination library not found.")
        else:
            self.remove_unpublished_templates(destination_library_id)  # Call before copying templates
            self.copy_templates_to_library(source_library_id, destination_library_id)
            self.delete_excess_templates(destination_library_id)

        self.module.exit_json(changed=True, msg="Library management succeeded")



def main():
    argument_spec = VmwareRestClient.vmware_client_argument_spec()
    argument_spec.update(
        hostname=dict(type='str', required=True),
        port=dict(type='int', default=443),
        username=dict(type='str', required=True),
        password=dict(type='str', required=True, no_log=True),
        validate_certs=dict(type='bool', default=False),
        source_library=dict(type='str', required=True),
        destination_library=dict(type='str', required=True)
    )

    module = AnsibleModule(argument_spec=argument_spec)
    vmware_content_library_manager = VMwareContentLibraryManager(module)

    vmware_content_library_manager.manage_content_libraries()


if __name__ == "__main__":
    main()
