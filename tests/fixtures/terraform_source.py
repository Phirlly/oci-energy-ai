from pathlib import Path


EXPECTED_MEMBERS = (
    ".terraform.lock.hcl", "locals.tf", "outputs.tf", "project.tf",
    "providers.tf", "storage.tf", "variables.tf", "versions.tf",
)


def write_terraform_source(root):
    source = Path(root) / "infra" / "terraform"
    source.mkdir(parents=True)
    for name in EXPECTED_MEMBERS:
        (source / name).write_text(f"# fixture {name}\n", encoding="utf-8")
    return source
