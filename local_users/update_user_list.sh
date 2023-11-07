#!/bin/sh

remove_user() {
    login="$1"
    FIRSTLINE=$(grep -n "name: $login" vars/main.yml | cut -d: -f1)
    ENDLINE=$(sed -n "$((FIRSTLINE+1)),\$p" vars/main.yml | grep -n 'name:' | head -n 1 | cut -d: -f1)
    ENDLINE=$((FIRSTLINE + ENDLINE - 1))
    if [ $_DRY_RUN -eq 0 ]; then
        sed -i "$FIRSTLINE,${ENDLINE}d" vars/main.yml
    fi
    echo "$login removed"
}

_DRY_RUN=1
if [ "$1" = "-f" ]; then
    _DRY_RUN=0
    shift
fi

if [ $# -eq 0 ]; then
    echo "Usage: $(basename $0) [-f] <ldap_password>"
    echo "When:"
    echo "  -f force execution (default is dry-run)"
    echo
    exit 1
fi

LDAP_PASSWORD="$1"

ldapsearch -h 10.2.0.6 -D ldapAmazon@imtf.com -w "${LDAP_PASSWORD}" -x -LLL -o nettimeout=1 \
           -b OU=Deactivated,OU=Domain_Users,OU=Users,OU=IMTF,DC=IMTF,DC=LOCAL \
           "(objectClass=user)" sAMAccountName | grep sAMAccountName | sed 's/sAMAccountName: //1' | tr 'A-Z' 'a-z' | while read login; do

    if grep -q "name: $login" vars/main.yml; then
        echo "$login found in vars/main.yml" >&2
        remove_user $login
    fi

done

python -c 'import yaml; print("\n".join(list(map(lambda x: x["name"], yaml.safe_load(open("vars/main.yml"))["user_dict"]))))' | while read login; do
    if ! ldapsearch -h 10.2.0.6 -D ldapAmazon@imtf.com -w "${LDAP_PASSWORD}" -x -LLL -o nettimeout=1 \
                    -b DC=IMTF,DC=LOCAL "(sAMAccountName=$login)" sAMAccountName | grep -q sAMAccountName; then
        if [ "$login" != "smiles" ] && [ "$login" != "alang" ]; then
            echo "$login not found in AD" >&2
            remove_user $login
        fi
    fi
done
