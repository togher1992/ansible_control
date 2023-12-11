#!/usr/bin/python

import json
import requests
import uuid
import urllib3
import time
from collections import defaultdict
from ansible.module_utils.basic import *
from ansible.module_utils.vmware_rest_client import VmwareRestClient
from ansible.module_utils._text import to_native
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class VMwareContentLibraryManager(VmwareRestClient):
    def __init__(self, module):
        """Constructor."""
        super(VMwareContentLibraryManager, self).__init__(module)
        self.hostname = self.params.get('hostname')
        self.content_library = self.params.get('content_library')
        self.vm_name = self.params.get('vm_name')
        self.validate_certs = self.params.get('validate_certs')
        self.username = self.params.get('username')
        self.password = self.params.get('password')
        self.esxi_host = self.params.get('esxi_host')
        self.vm_notes = self.params.get('vm_notes')
        self.port = self.params.get('port')
        self.new_template_name = self.params.get('new_template_name')

        # Session management
        self.session = self.get_vcenter_session()

    def api_call(self, url, method='get', headers=None, **kwargs):
        response = getattr(requests, method)(url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json() if response.text else None

    def get_vcenter_session(self):
        url = f"https://{self.hostname}/rest/com/vmware/cis/session"
        response = requests.post(url, auth=(self.username, self.password), verify=self.validate_certs)
        response.raise_for_status()
        return response.json()

    def get_vm_id(self):
        url = f"https://{self.hostname}/rest/vcenter/vm?filter.names={self.vm_name}"
        headers = {'vmware-api-session-id': self.session['value']}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data['value'][0]['vm'] if data else None

    def get_lib_id(self):
        url = f"https://{self.hostname}/rest/com/vmware/content/library?~action=find"
        headers = {'vmware-api-session-id': self.session['value']}
        params = {'spec': {'name': self.content_library, 'type': 'LOCAL'}}
        data = self.api_call(url, method='post', headers=headers, json=params, verify=self.validate_certs)
        return data['value'] if data else None

    def check_content_library_state(self):
        lib_id = self.get_lib_id()
        return 'present' if lib_id else 'absent'
  
    def check_vm_state(self):
        lib_id = self.get_vm_id()
        return 'present' if lib_id else 'absent'

    def add_vm_to_content_library(self):
        vm_id = self.get_vm_id()
        lib_id = self.get_lib_id()

        url = f"https://{self.hostname}/rest/com/vmware/vcenter/ovf/library-item"
        headers = {
            'vmware-api-session-id': self.session['value'],
            'Content-Type': 'application/json'
        }
        payload = {
            "create_spec": {
                "name": f"{self.new_template_name}"
            },
            "source": {
                "id": f"{vm_id}",
                "type": "VirtualMachine"
            },
            "target": {
                "library_id": f"{lib_id[0]}"
            }
        }
        response = self.api_call(url, method='post', headers=headers, json=payload, verify=self.validate_certs)
        if not response or response.get('succeeded') is False:
            self.module.fail_json(msg=f"Failed to add VM: {self.vm_name} to Content Library: {self.content_library}.")
        
        self.remove_excess_templates(lib_id=lib_id[0])
        self.publish_template(lib_id=lib_id[0])

    def get_all_template_ids(self, lib_id):
        url = f"https://{self.hostname}/rest/com/vmware/content/library/item?library_id={lib_id}"
        headers = {'vmware-api-session-id': self.session['value']}
        data = self.api_call(url, method='get', headers=headers, verify=self.validate_certs)
        if data:
            templates = []
            for item in data['value']:
                if item:
                    template_id = item.replace('"', '')
                    template_name = self.get_template_name(template_id)
                    template_notes = self.get_template_notes(template_id)
                    vm_name = template_name.split('_')[0] if '_' in template_name else template_name
                    templates.append((template_id, vm_name, template_name, template_notes))
            return templates
        else:
            return None
            
    def publish_template(self, lib_id):
        template_data = self.get_all_template_ids(lib_id)
        if template_data:
            templates_by_vm = defaultdict(list)
            for template_id, vm_name, template_name, template_notes in template_data:
                templates_by_vm[vm_name].append((template_id, template_name, template_notes))
            for vm_name, templates in templates_by_vm.items():
                templates.sort(key=lambda x: x[1], reverse=True)
                for template_id, template_name, template_notes in templates:
                    if vm_name == self.vm_name:  # Only update notes if VM names match
                        if template_notes:
                            notes=json.loads(template_notes.replace("'",'"'))
                            if notes['published'] and notes['published'] == 'False':
                                notes['published'] = 'True'
                            elif notes['published'] and notes['published'] == 'True':
                                notes['published'] = 'Retired'
                            url = f"https://{self.hostname}/rest/com/vmware/content/library/item/id:{template_id}"
                            headers = {'vmware-api-session-id': self.session['value']}
                            payload = { 'update_spec': { 'description': f'{notes}' }}
                            response = requests.patch(url, headers=headers, json=payload, verify=self.validate_certs)
                            if response.status_code != 200:
                                self.module.fail_json(msg=f"Failed to update published status of template: {template_name} with ID: {template_id[0]}")

    def get_template_name(self, template_id):
        url = f"https://{self.hostname}/rest/com/vmware/content/library/item/id:{template_id}"
        headers = {'vmware-api-session-id': self.session['value']}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data['value'].get('name', '') if data else ''
        
    def get_template_notes(self, template_id):
        url = f"https://{self.hostname}/rest/com/vmware/content/library/item/id:{template_id}"
        headers = {'vmware-api-session-id': self.session['value']}
        data = self.api_call(url, headers=headers, verify=self.validate_certs)
        return data['value'].get('description', '') if data else ''

    def remove_excess_templates(self, lib_id):
        template_data = self.get_all_template_ids(lib_id)
        if template_data:
            templates_by_vm = defaultdict(list)
            for template_id, vm_name, template_name, template_notes in template_data:
                templates_by_vm[vm_name].append((template_id, template_name))
            for vm_name, templates in templates_by_vm.items():
                templates.sort(key=lambda x: x[1], reverse=True)
                if len(templates) > 2:
                    for template_id, template_name in templates[2:]:
                        url = f"https://{self.hostname}/rest/com/vmware/content/library/item/id:{template_id}"
                        headers = {'vmware-api-session-id': self.session['value']}
                        response = requests.delete(url, headers=headers, verify=self.validate_certs)
                        if response.status_code != 200:
                            self.module.fail_json(msg=f"Failed to delete template with ID: {template_id}")

    def process_state(self):
        if self.check_content_library_state() == 'absent':
            self.module.fail_json(msg=f"Content Library '{self.content_library}' does not exist.")
        if self.check_vm_state() == 'absent':
            self.module.fail_json(msg=f"Virtual Machine Source '{self.vm_name}' does not exist")
        self.add_vm_to_content_library()


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            content_library=dict(type='str', required=True),
            vm_name=dict(type='str', required=True),
            validate_certs=dict(type='bool', default=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            esxi_host=dict(type='str', required=True),
            vm_notes=dict(type='str', default=''),
            port=dict(type='int', default=443),
            new_template_name=dict(type='str', required=True)
        ),
    )

    vmware_content_library_manager = VMwareContentLibraryManager(module)
    vmware_content_library_manager.process_state()
    module.exit_json(changed=False)


if __name__ == '__main__':
    main()
