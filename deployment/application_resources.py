"""Discover pinned topology and verify dedicated resource ownership before use or cleanup."""

from oci.exceptions import ServiceError

from deployment.application_configuration import ApplicationConfiguration, regional_identifier
from deployment.configuration import DeploymentError
from deployment.resource_jobs import retry_token


_SHAPE = 'VM.Standard.E5.Flex'
_RETIRED = {'PENDING_DELETION', 'SCHEDULING_DELETION', 'DELETING', 'DELETED'}


class ApplicationResources:
    def __init__(self, clients, config, deadline):
        self.clients, self.config, self.deadline = clients, config, deadline
        self.name = f'oci-energy-ai-{config.deployment_id}'
        self.tags = {'application': 'oci-energy-ai', 'deployment_id': config.deployment_id, 'managed_by': 'terraform'}

    def _owned(self, item, kind, *, name=None):
        if (not regional_identifier(item.id, kind, self.config.region)
                or item.compartment_id != self.config.compartment_ocid
                or item.display_name != (name or self.name)
                or any((item.freeform_tags or {}).get(k) != v for k, v in self.tags.items())):
            raise DeploymentError('OCI resource ownership does not match; refusing adoption or cleanup.')

    def _matching(self, item):
        tags = item.freeform_tags or {}
        return item.display_name == self.name or (
            tags.get('application') == 'oci-energy-ai' and tags.get('deployment_id') == self.config.deployment_id)

    def topology(self, tenancy, environment, *, pinned=None):
        subscriptions = list(self.deadline.pages(self.clients.identity.list_region_subscriptions, tenancy))
        ready = {item.region_name for item in subscriptions if item.status == 'READY'}
        home = [item.region_name for item in subscriptions if item.is_home_region and item.status == 'READY']
        if self.config.region not in ready or len(home) != 1:
            raise DeploymentError('Required OCI region subscription is not ready.')
        domains = sorted(item.name for item in self.deadline.pages(
            self.clients.identity.list_availability_domains, self.config.compartment_ocid))
        if not domains:
            raise DeploymentError('No available OCI availability domain was returned.')
        if pinned is not None:
            if (pinned.tenancy_ocid != tenancy or pinned.home_region != home[0]
                    or environment.get('OCI_AVAILABILITY_DOMAIN') not in (None, '', pinned.availability_domain)
                    or environment.get('OCI_IMAGE_OCID') not in (None, '', pinned.image_ocid)):
                raise DeploymentError('Requested topology differs from the pinned deployment.')
            domain, image_id = pinned.availability_domain, pinned.image_ocid
        else:
            domain = environment.get('OCI_AVAILABILITY_DOMAIN') or domains[0]
            image_id = environment.get('OCI_IMAGE_OCID')
            if not image_id:
                images = self.deadline.pages(self.clients.compute.list_images, self.config.compartment_ocid,
                    operating_system='Oracle Linux', shape=_SHAPE, lifecycle_state='AVAILABLE',
                    sort_by='TIMECREATED', sort_order='DESC')
                image_id = next((item.id for item in images if item.compartment_id is None
                                 and isinstance(item.operating_system_version, str)
                                 and item.operating_system_version.split('.')[0] == '9'), None)
        if domain not in domains or not regional_identifier(image_id, 'image', self.config.region):
            raise DeploymentError('No valid selected OCI image or availability domain.')
        image = self.deadline.call(self.clients.compute.get_image, image_id).data
        compatible = self.deadline.call(self.clients.compute.get_image_shape_compatibility_entry, image_id, _SHAPE).data
        if (image.id != image_id or image.compartment_id is not None or image.lifecycle_state != 'AVAILABLE'
                or image.operating_system != 'Oracle Linux' or not isinstance(image.operating_system_version, str)
                or image.operating_system_version.split('.')[0] != '9'
                or compatible.image_id != image_id or compatible.shape != _SHAPE):
            raise DeploymentError('Selected platform image is not compatible with the verified host.')
        return ApplicationConfiguration(1, tenancy, home[0], domain, image_id)

    def _bucket(self, namespace):
        def get():
            try:
                return self.clients.storage.get_bucket(namespace, self.name + '-artifacts')
            except ServiceError as error:
                if error.status == 404:
                    return None
                raise
        result = self.deadline.call(get)
        if result is None:
            return None
        bucket = result.data
        if (bucket.name != self.name + '-artifacts' or bucket.namespace != namespace
                or bucket.compartment_id != self.config.compartment_ocid
                or bucket.public_access_type != 'NoPublicAccess' or bucket.versioning != 'Disabled'
                or any((bucket.freeform_tags or {}).get(k) != v for k, v in self.tags.items())):
            raise DeploymentError('Artifact bucket ownership or private-storage settings do not match.')
        return bucket

    def _keys(self, vault):
        client = self.clients.keys(vault.management_endpoint)
        keys = list(self.deadline.pages(client.list_keys, self.config.compartment_ocid))
        if len(keys) > 1:
            raise DeploymentError('Dedicated Vault contains unknown or duplicate keys; cleanup refused.')
        if not keys:
            return None
        summary = keys[0]
        self._owned(summary, 'key', name=self.name + '-secrets')
        key = self.deadline.call(client.get_key, summary.id).data
        self._owned(key, 'key', name=self.name + '-secrets')
        if (key.id != summary.id or key.protection_mode != 'SOFTWARE'
                or key.key_shape.algorithm != 'AES' or key.key_shape.length != 32
                or key.lifecycle_state not in {'ENABLED', 'PENDING_DELETION', 'SCHEDULING_DELETION'}):
            raise DeploymentError('Dedicated Vault key is invalid or unusable.')
        return key

    def discover(self):
        instances, vaults, retired = [], [], 0
        for item in self.deadline.pages(self.clients.compute.list_instances, self.config.compartment_ocid):
            if item.lifecycle_state == 'TERMINATED' or not self._matching(item):
                continue
            self._owned(item, 'instance')
            instances.append(item)
        for item in self.deadline.pages(self.clients.kms.list_vaults, self.config.compartment_ocid):
            if not self._matching(item):
                continue
            self._owned(item, 'vault')
            if item.lifecycle_state in _RETIRED:
                retired += 1
            else:
                vaults.append(item)
        if len(instances) > 1 or len(vaults) > 1:
            raise DeploymentError('Multiple current OCI resources match; resolve before deployment.')
        namespace = self.deadline.call(self.clients.storage.get_namespace).data
        vault, key = None, None
        if vaults:
            vault = self.deadline.call(self.clients.kms.get_vault, vaults[0].id).data
            self._owned(vault, 'vault')
            if vault.id != vaults[0].id or vault.lifecycle_state != 'ACTIVE' or vault.vault_type != 'DEFAULT':
                raise DeploymentError('Owned Vault is not active; inspect before retrying.')
            key = self._keys(vault)
        return dict(instance=instances[0] if instances else None, vault=vault, key=key,
                    retired_vaults=retired, namespace=namespace, bucket=self._bucket(namespace))

    def verify_outputs(self, outputs, topology):
        inventory = self.discover()
        instance, vault, key = (inventory[name] for name in ('instance', 'vault', 'key'))
        if (instance is None or vault is None or key is None or inventory['bucket'] is None
                or instance.id != outputs['instance_ocid'] or instance.lifecycle_state != 'RUNNING'
                or instance.shape != _SHAPE or instance.availability_domain != topology.availability_domain
                or instance.source_details is None or instance.source_details.source_type != 'image'
                or instance.source_details.image_id != topology.image_ocid
                or vault.id != outputs['vault_ocid'] or key.id != outputs['key_ocid']
                or key.lifecycle_state != 'ENABLED' or inventory['namespace'] != outputs['object_storage_namespace']
                or inventory['bucket'].name != outputs['artifact_bucket_name']):
            raise DeploymentError('Application outputs do not identify the current owned resources.')
        project = self.deadline.call(self.clients.genai.get_generative_ai_project,
                                     outputs['generative_ai_project_ocid']).data
        self._owned(project, 'generativeaiproject')
        if project.id != outputs['generative_ai_project_ocid'] or project.lifecycle_state != 'ACTIVE':
            raise DeploymentError('Application project is not active.')
        gateways = [item for item in self.deadline.pages(self.clients.gateway.list_gateways,
                    self.config.compartment_ocid, collection=True)
                    if item.lifecycle_state != 'DELETED' and self._matching(item)]
        if len(gateways) != 1:
            raise DeploymentError('Application gateway is missing or ambiguous.')
        gateway = gateways[0]
        self._owned(gateway, 'apigateway')
        if (gateway.lifecycle_state != 'ACTIVE' or gateway.endpoint_type != 'PUBLIC'
                or 'https://' + gateway.hostname != outputs['application_origin']):
            raise DeploymentError('Application gateway does not match the hosted origin.')
        attached = list(self.deadline.pages(self.clients.compute.list_vnic_attachments,
            self.config.compartment_ocid, instance_id=instance.id))
        vnics = []
        for item in attached:
            if item.instance_id != instance.id:
                raise DeploymentError('VNIC attachment identity does not match the application host.')
            if item.lifecycle_state != 'ATTACHED':
                continue
            vnic = self.deadline.call(self.clients.network.get_vnic, item.vnic_id).data
            if vnic.id != item.vnic_id or vnic.compartment_id != self.config.compartment_ocid:
                raise DeploymentError('VNIC response identity does not match the owned attachment.')
            vnics.append(vnic)
        if (len(vnics) != 1 or vnics[0].public_ip is not None
                or vnics[0].private_ip + ':8080' != outputs['backend_host']):
            raise DeploymentError('Application backend is not the owned private host.')
        return inventory

    def stop(self, instance):
        while True:
            result = self.deadline.call(self.clients.compute.get_instance, instance.id)
            current = result.data
            self._owned(current, 'instance')
            if current.id != instance.id:
                raise DeploymentError('Host identity changed; cleanup refused.')
            if current.lifecycle_state in {'STOPPED', 'TERMINATED'}:
                return
            if current.lifecycle_state == 'RUNNING':
                etag = result.headers.get('etag')
                if not isinstance(etag, str) or not etag:
                    raise DeploymentError('Host ETag missing; cleanup refused.')
                self.deadline.call(self.clients.compute.instance_action, instance.id, 'STOP', if_match=etag,
                                   opc_retry_token=retry_token(instance.id, 'cleanup-stop', etag))
            elif current.lifecycle_state not in {'PROVISIONING', 'STARTING', 'STOPPING', 'TERMINATING'}:
                raise DeploymentError('Host cannot be proved stopped; cleanup refused.')
            self.deadline.pause()
