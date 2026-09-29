#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

assert_contains() {
    [[ "$1" == *"$2"* ]] || fail "expected output to contain [$2]"
}

assert_not_contains() {
    [[ "$1" != *"$2"* ]] || fail "output unexpectedly contained [$2]"
}

[[ -x scripts/bootstrap-oci-state.sh ]] || fail "scripts/bootstrap-oci-state.sh is missing"
[[ -x scripts/import-oci-existing.sh ]] || fail "scripts/import-oci-existing.sh is missing"

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
fake_bin="$test_root/bin"
mkdir -p "$fake_bin"
oci_log="$test_root/oci.log"
terraform_log="$test_root/terraform.log"

cat >"$fake_bin/oci" <<'FAKE_OCI'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$OCI_LOG"
command_line="$*"

case "$command_line" in
    "iam availability-domain list"*) printf 'tenancy-ocid\n' ;;
    "iam compartment list"*)
        if [[ "$command_line" == *"data[0].id"* ]]; then
            printf 'app-compartment-ocid\n'
        else
            case "${FAKE_OCI_MODE:-missing}" in
                missing) printf '0\n' ;;
                empty) : ;;
                existing) printf '1\n' ;;
                ambiguous) printf '2\n' ;;
            esac
        fi
        ;;
    "iam compartment create"*)
        if [[ "${FAKE_OCI_MODE:-missing}" != "empty" ]]; then
            printf 'app-compartment-ocid\n'
        fi
        ;;
    "iam compartment get"*) printf 'ACTIVE\n' ;;
    "os ns get"*) printf 'test-namespace\n' ;;
    "os bucket list"*)
        case "${FAKE_OCI_MODE:-missing}" in
            missing) printf '0\n' ;;
            empty) : ;;
            *) printf '1\n' ;;
        esac
        ;;
    "os bucket create"*) printf 'learningx-alert-tfstate\n' ;;
    "os bucket update"*) printf 'learningx-alert-tfstate\n' ;;
    *) exit 91 ;;
esac
FAKE_OCI

cat >"$fake_bin/terraform" <<'FAKE_TERRAFORM'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$TERRAFORM_LOG"
if [[ "$*" == *" console "* || "$*" == *" console" ]]; then
    read -r expression
    case "$expression" in
        var.app_compartment_ocid) printf '"app-compartment-ocid"\n' ;;
        var.object_storage_namespace) printf '"test-namespace"\n' ;;
        var.instance_ocid) printf '"instance-ocid"\n' ;;
        var.vcn_ocid) printf '"vcn-ocid"\n' ;;
        var.subnet_ocid) printf '"subnet-ocid"\n' ;;
        var.reserved_public_ip_ocid) printf '"public-ip-ocid"\n' ;;
        *) exit 92 ;;
    esac
    exit 0
fi
if [[ "$*" == *" state show "* ]]; then
    exit 1
fi
if [[ "$*" == *" import "* ]]; then
    exit 0
fi
exit 93
FAKE_TERRAFORM
chmod +x "$fake_bin/oci" "$fake_bin/terraform"

missing_output=$(
    OCI_BIN="$fake_bin/oci" \
    OCI_LOG="$oci_log" \
    FAKE_OCI_MODE=missing \
    bash scripts/bootstrap-oci-state.sh
)
assert_contains "$missing_output" "app_compartment_id=app-compartment-ocid"
assert_contains "$missing_output" "namespace=test-namespace"
missing_log=$(<"$oci_log")
assert_contains "$missing_log" "iam compartment create"
assert_contains "$missing_log" "os bucket create"
assert_contains "$missing_log" "--versioning Enabled"
assert_not_contains "$missing_log" "os bucket list --compartment-id app-compartment-ocid --namespace-name test-namespace --name"
assert_not_contains "$missing_log" "--access-type"

: >"$oci_log"
empty_output=$(
    OCI_BIN="$fake_bin/oci" \
    OCI_LOG="$oci_log" \
    FAKE_OCI_MODE=empty \
    bash scripts/bootstrap-oci-state.sh
)
assert_contains "$empty_output" "app_compartment_id=app-compartment-ocid"
empty_log=$(<"$oci_log")
assert_contains "$empty_log" "iam compartment create"
assert_contains "$empty_log" "os bucket create"

: >"$oci_log"
existing_output=$(
    OCI_BIN="$fake_bin/oci" \
    OCI_LOG="$oci_log" \
    FAKE_OCI_MODE=existing \
    bash scripts/bootstrap-oci-state.sh
)
assert_contains "$existing_output" "app_compartment_id=app-compartment-ocid"
existing_log=$(<"$oci_log")
assert_not_contains "$existing_log" "iam compartment create"
assert_not_contains "$existing_log" "os bucket create"
assert_contains "$existing_log" "os bucket update"
assert_not_contains "$existing_log" "--force"

: >"$oci_log"
set +e
ambiguous_output=$(
    OCI_BIN="$fake_bin/oci" \
    OCI_LOG="$oci_log" \
    FAKE_OCI_MODE=ambiguous \
    bash scripts/bootstrap-oci-state.sh 2>&1
)
ambiguous_status=$?
set -e
[[ $ambiguous_status -ne 0 ]] || fail "ambiguous compartment unexpectedly succeeded"
assert_contains "$ambiguous_output" "ambiguous app compartment"
ambiguous_log=$(<"$oci_log")
assert_not_contains "$ambiguous_log" "iam compartment create"
assert_not_contains "$ambiguous_log" "os bucket create"

TERRAFORM_BIN="$fake_bin/terraform" \
TERRAFORM_LOG="$terraform_log" \
bash scripts/import-oci-existing.sh
import_log=$(<"$terraform_log")
for address in \
    oci_identity_compartment.app \
    oci_objectstorage_bucket.terraform_state \
    oci_core_instance.app_host \
    oci_core_vcn.existing \
    oci_core_subnet.existing \
    oci_core_public_ip.reserved; do
    assert_contains "$import_log" "import -var-file=terraform.tfvars $address"
done
assert_contains "$import_log" "n/test-namespace/b/learningx-alert-tfstate"

printf 'terraform_workflow_test: PASS\n'
