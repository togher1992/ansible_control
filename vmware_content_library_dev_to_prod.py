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

        # Initializing the count variables for source and destination OS versions
        self.source_os_version_count = defaultdict(int)
        self.destination_os_version_count = defaultdict(int)

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

    def remove_unpublished_templates(self, library_id):
        templates = self.get_all_template_ids(library_id)
        for template_id, _, _, template_notes in templates:
            if self.check_template_published(template_notes) == 'False':
                self.delete_template_from_library(template_id, library_id)

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
                    operating_system_version = None
                    if template_notes:
                        notes = json.loads(template_notes.replace("'", '"'))
                        operating_system_version = notes.get('operatingSystemVersion', None)
                    templates.append((template_id, operating_system_version, template_name, template_notes))
        return templates

    def check_template_published(self, template_notes):
        if template_notes:
            notes = json.loads(template_notes.replace("'", '"'))
            return notes.get('published', 'False')
        return 'False'

    def copy_templates_to_library(self, source_library_id, destination_library_id):
        source_templates = self.get_all_template_ids(source_library_id)
        destination_templates = self.get_all_template_ids(destination_library_id)

        if source_templates:
            for template_id, os_version, template_name, template_notes in source_templates:
                published_status = self.check_template_published(template_notes)
                if published_status == 'True':  # Only copy templates with 'True' status
                    if not any(d_template_name == template_name for _, _, d_template_name, _ in destination_templates):
                        self.copy_template_to_library(template_id, template_name, destination_library_id)

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

    def delete_template_from_library(self, template_id, library_id):
        url = f"https://{self.hostname}/api/content/library/item/{template_id}"
        headers = {'vmware-api-session-id': self.session}
        response = requests.delete(url, headers=headers, verify=self.validate_certs)
        if response.status_code != 204:
            self.module.fail_json(msg="Failed to delete template.")
            
    def remove_excess_templates(self, library_id):
        # Getting all templates
        templates = self.get_all_template_ids(library_id)

        # Grouping templates by operatingSystemVersion
        os_version_templates = defaultdict(lambda: {'True': [], 'False': [], 'Retired': []})
        for template in templates:
            template_id, os_version, _, template_notes = template
            if os_version:
                notes = json.loads(template_notes.replace("'", '"'))
                published_status = notes.get('published', 'False')
                os_version_templates[os_version][published_status].append(template_id)

        # Processing each OS version group
        for _, template_lists in os_version_templates.items():
            # Keep the latest 'True' template and remove the others
            for template_id in template_lists['True'][:-1]:
                self.delete_template_from_library(template_id, library_id)

            # Keep only the latest 'False' template and remove the others
            for template_id in template_lists['False'][:-1]:
                self.delete_template_from_library(template_id, library_id)

            # Remove all 'Retired' templates only if there is at least one 'False' template
            if template_lists['False']:
                for template_id in template_lists['Retired']:
                    self.delete_template_from_library(template_id, library_id)


    def main(self):
        """Main entry point of the module."""
        source_library_id = self.get_source_library_id()
        source_library_state = self.check_content_library_state(source_library_id)

        destination_library_id = self.get_destination_library_id()
        destination_library_state = self.check_content_library_state(destination_library_id)

        if source_library_state == 'absent':
            self.module.fail_json(msg="Source library not found.")
        elif destination_library_state == 'absent':
            self.module.fail_json(msg="Destination library not found.")
        else:
            self.remove_unpublished_templates(destination_library_id)
            self.copy_templates_to_library(source_library_id, destination_library_id)
            self.remove_excess_templates(destination_library_id)

            self.module.exit_json(
                msg="Templates copied successfully.",
                source_library=self.source_library,
                destination_library=self.destination_library,
            )


def main():
    argument_spec = VmwareRestClient.vmware_client_argument_spec()
    argument_spec.update(
        hostname=dict(type='str', required=True),
        username=dict(type='str', required=True),
        password=dict(type='str', required=True, no_log=True),
        port=dict(type='int', default=443),
        source_library=dict(type='str', required=True),
        destination_library=dict(type='str', required=True),
        validate_certs=dict(type='bool', default=False)
    )

    module = AnsibleModule(argument_spec=argument_spec)

    vmware_content_lib_mgr = VMwareContentLibraryManager(module)
    vmware_content_lib_mgr.main()


if __name__ == '__main__':
    main()
