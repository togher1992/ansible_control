#!/usr/bin/python

from ansible.module_utils.basic import AnsibleModule
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def add_content_library(module):
    # Get module parameters
    source_library_name = module.params.get('source_library_name')
    destination_library_name = module.params.get('destination_library_name')
    vcenter_host = module.params.get('vcenter_host')
    vcenter_user = module.params.get('vcenter_user')
    vcenter_password = module.params.get('vcenter_password')
    validate_certs = module.params.get('validate_certs')

    try:
        # Disable SSL certificate verification
        context = None
        if not validate_certs:
            context = create_ssl_context()

        # Connect to vCenter
        service_instance = SmartConnect(
            host=vcenter_host,
            user=vcenter_user,
            pwd=vcenter_password,
            sslContext=context
        )
        if not service_instance:
            module.fail_json(msg='Unable to connect to vCenter')

        # Get source and destination libraries
        source_library = get_content_library_by_name(service_instance, source_library_name)
        if not source_library:
            module.fail_json(msg=f'Source library "{source_library_name}" not found')
        destination_library = get_content_library_by_name(service_instance, destination_library_name)
        if not destination_library:
            module.fail_json(msg=f'Destination library "{destination_library_name}" not found')

        # Get items from source library
        items = source_library.item

        # Filter out items with annotation { "published":"false" }
        filtered_items = [item for item in items if not is_item_published_false(item)]

        # Add filtered items to destination library
        for item in filtered_items:
            add_item_to_library(service_instance, item, destination_library)

        # Disconnect from vCenter
        Disconnect(service_instance)

        module.exit_json(changed=True, msg=f'Added items from "{source_library_name}" to "{destination_library_name}"')
    except Exception as e:
        module.fail_json(msg=str(e))


def create_ssl_context():
    # Create a custom SSLContext with check_hostname set to False
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def get_content_library_by_name(service_instance, library_name):
    content_manager = service_instance.content.rootFolder.childEntity
    for entity in content_manager:
        if isinstance(entity, vim.ContentLibrary) and entity.name == library_name:
            return entity
    return None


def is_item_published_false(item):
    annotations = item.GetAnnotation()
    for annotation in annotations:
        if annotation.key == 'published' and annotation.value == 'false':
            return True
    return False


def add_item_to_library(service_instance, item, library):
    try:
        library_item = library.AddLibraryItem(name=item.GetName(), item=item)
        library_item.Update()
    except Exception as e:
        raise Exception(f'Failed to add item "{item.GetName()}" to library: {str(e)}')


def main():
    module_args = dict(
        source_library_name=dict(type='str', required=True),
        destination_library_name=dict(type='str', required=True),
        vcenter_host=dict(type='str', required=True),
        vcenter_user=dict(type='str', required=True),
        vcenter_password=dict(type='str', required=True, no_log=True),
        validate_certs=dict(type='bool', required=False, default=True)
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if module.check_mode:
        module.exit_json(changed=False)

    add_content_library(module)


if __name__ == '__main__':
    main()
