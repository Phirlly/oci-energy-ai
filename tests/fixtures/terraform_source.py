from pathlib import Path


EXPECTED_MEMBERS = (
    ".terraform.lock.hcl", "compute.tf", "console.tf", "console_images.tf", "console_variables.tf", "gateway.tf", "locals.tf", "network.tf", "network_access.tf",
    "outputs.tf", "project.tf", "providers.tf", "runtime_identity.tf", "storage.tf", "variables.tf",
    "settings.tf", "vault.tf", "versions.tf",
    "host/__init__.py", "host/activation.py", "host/artifacts.py", "host/bootstrap.sh",
    "host/console_contract.py", "host/console_install.py", "host/console_sources.py", "host/contracts.py",
    "host/control.py", "host/entrypoint.py", "host/install_entry.py", "host/oci-energy-ai-install.service",
    "host/oci-energy-ai-install.timer", "host/oci-energy-ai.service", "host/process.py",
    "host/service.py", "host/service_entry.py", "host/state.py",
)


def write_terraform_source(root):
    source = Path(root) / "infra" / "terraform"
    source.mkdir(parents=True)
    for name in EXPECTED_MEMBERS:
        (source / name).parent.mkdir(exist_ok=True)
        (source / name).write_text(f"# fixture {name}\n", encoding="utf-8")
    return source
