# Sample session (ILLUSTRATIVE)

This transcript shows the expected interaction format. Model wording will vary. The tool results
inside it correspond to real outputs in `real_integration_output.txt`, which was executed.

```
agent23> create a group called developers, then create user alice (Alice Smith) in it with a projects/web folder

  > tool: get_group_info {'groupname': 'developers'}
  > tool: create_group {'groupname': 'developers'}
  Execute `groupadd developers` ? [y/N] y
  > tool: create_user {'username': 'alice', 'groups': ['developers'], 'comment': 'Alice Smith'}
  Execute `useradd -m -s /bin/bash -c 'Alice Smith' -G developers alice` ? [y/N] y
  > tool: create_directory {'username': 'alice', 'relative_path': 'projects/web', 'mode': '700'}
  Execute `runuser -u alice -- mkdir -p -m 700 /home/alice/projects/web` ? [y/N] y

Done, all verified: group developers created; user alice (uid 1001) with home /home/alice, shell
/bin/bash, member of developers; /home/alice/projects/web exists, owned by alice, mode 700.
No password is set; run `sudo passwd alice` if needed.

agent23> add alice to sudo
  > tool: add_user_to_groups {'username': 'alice', 'groups': ['sudo']}
  ! PRIVILEGED GROUP(S): sudo grant elevated system rights.
  Execute `usermod -a -G sudo alice` ? [y/N] n

The operator declined, so alice was not added to sudo.

agent23> make a folder ../../etc/x for alice
  > tool: create_directory {'username': 'alice', 'relative_path': '../../etc/x'}

Refused: validation rejected the path ('..' is not allowed). Folders must be inside alice's home.
```
