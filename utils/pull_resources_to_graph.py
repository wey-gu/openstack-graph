#!/usr/bin/env python3
"""
Pull resource data from OpenStack and output DDL for NebulaGraph
Resources:
- images
- keypairs
- volume snapshots
Relations:
- glance_used_by:
  image -[:used_by]-> instance (get from instance)
- glance_created_from:
  image -[:created_from]-> volume (get from image) ----mocked
- nova_keypair_used_by:
  keypair -[:used_by]-> instance (get from instance)
- cinder_snapshot_created_from:
  volume snapshot -[:created_from]-> volume (get from snapshot)
- cinder_volume_created_from:
  volume -[:created_from]-> volume snapshot (get from volume)
- cinder_volume_created_from:
  volume -[:created_from]-> image (get from volume)

Note, there is order required due to we are using name as VID
Thus we need to ensure uuid_to_vertex_id for given resource is created before
it's called, that is, we should execute in this order

- cinder_volume_created_from
- cinder_snapshot_created_from(dependent on cinder_volume_created_from)
- glance_created_from(dependent on cinder_volume_created_from) ----mocked
- glance_used_by(dependent on glance_created_from)
- nova_keypair_used_by(dependent on nova_keypairs)
"""

# import glance, cinder, nova clients


import csv
import json
import os
import subprocess

import glanceclient

from collections import defaultdict

from keystoneauth1.identity import v3
from keystoneauth1 import session, loading
from novaclient import client as nova_client
from cinderclient import client as cinder_client


uuid_to_vertex_id = defaultdict(str)
_q = '"'


def get_session():
    OPENRC = "openrc"

    if os.path.isfile(f"./OPENRC"):
        try:
            process = subprocess.Popen(
                f"source {OPENRC} admin admin", shell=True, executable="/bin/bash"
            )
            process.wait()
        except subprocess.CalledProcessError as e:
            print(f"Error sourcing openrc file: {e}")
            exit(1)

        else:
            print(f"openrc file not found at: {OPENRC}")
            exit(1)

    # Access the environment variables
    AUTH_URL = os.environ.get("OS_AUTH_URL")
    USERNAME = os.environ.get("OS_USERNAME")
    PASSWORD = os.environ.get("OS_PASSWORD")
    PROJECT_NAME = os.environ.get("OS_PROJECT_NAME")
    USER_DOMAIN_ID = os.environ.get("OS_USER_DOMAIN_ID")
    PROJECT_DOMAIN_ID = os.environ.get("OS_PROJECT_DOMAIN_ID")

    # OpenStack Keystone Authentication
    auth = v3.Password(
        auth_url=AUTH_URL,
        username=USERNAME,
        password=PASSWORD,
        project_name=PROJECT_NAME,
        user_domain_id=USER_DOMAIN_ID,
        project_domain_id=PROJECT_DOMAIN_ID,
    )
    sess = session.Session(auth=auth)
    return sess


def get_all_images():
    """Get all images from OpenStack Glance"""
    sess = get_session()
    glance = glanceclient.Client("2", session=sess)
    images = glance.images.list()
    return images


def get_all_keypairs():
    """Get all keypairs from OpenStack Nova"""
    sess = get_session()
    nova = nova_client.Client("2", session=sess)
    keypairs = nova.keypairs.list()
    return keypairs


def get_all_volumes():
    """Get all volumes from OpenStack Cinder"""
    sess = get_session()
    cinder = cinder_client.Client("3", session=sess)
    volumes = cinder.volumes.list(search_opts={"all_tenants": 1})
    return volumes


def get_all_volume_snapshots():
    """Get all volume snapshots from OpenStack Cinder"""
    sess = get_session()
    cinder = cinder_client.Client("3", session=sess)
    volume_snapshots = cinder.volume_snapshots.list()
    return volume_snapshots


def get_all_instances():
    """Get all instances from OpenStack Nova"""
    sess = get_session()
    nova = nova_client.Client("2", session=sess)
    instances = nova.servers.list()
    return instances


def write_file(filename, lines):
    """Write lines to file"""
    with open(filename, "w") as f:
        f.writelines(lines)


def generate_volumes_rels_ddl_dml():
    """Generate DDL and DML for volume relations"""
    cinder_volume_snapshot_query_lines = [
        "CREATE TAG IF NOT EXISTS volume_snapshot( "
        "id string, name string, description string, "
        "status string, size int, volume_id string);\n"
    ]

    # volume -[:created_from]-> volume snapshot
    cinder_volume_created_from_snapshot_query_lines = [
        "CREATE EDGE IF NOT EXISTS created_from();\n"
    ]

    for snapshot in get_all_volume_snapshots():
        # this is for demo purposes only, we even assume name is unique
        vertex_id = snapshot.name if snapshot.name else snapshot.id
        uuid_to_vertex_id[snapshot.id] = vertex_id
        cinder_volume_snapshot_query_lines.append(
            f"INSERT VERTEX volume_snapshot("
            f"id, name, description, status, size, volume_id) VALUES "
            f"{_q}{vertex_id}{_q}:({_q}{snapshot.id}{_q}, "
            f"{_q}{snapshot.name}{_q}, {_q}{snapshot.description}{_q}, "
            f"{_q}{snapshot.status}{_q}, {snapshot.size}, "
            f"{_q}{snapshot.volume_id}{_q});\n"
        )

    for volume in get_all_volumes():
        # this is for demo purposes only, we even assume name is unique
        vertex_id = volume.name if volume.name else volume.id
        uuid_to_vertex_id[volume.id] = vertex_id
        if volume.snapshot_id:
            src = vertex_id
            dst = uuid_to_vertex_id[volume.snapshot_id]
            cinder_volume_created_from_snapshot_query_lines.append(
                f"INSERT EDGE created_from() VALUES "
                f"{_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )
    write_file(
        "vertices/cinder.volume_snapshot.ngql",
        cinder_volume_snapshot_query_lines,
    )
    write_file(
        "edges/cinder.volume.created_from.snapshot.ngql",
        cinder_volume_created_from_snapshot_query_lines,
    )


def generate_volume_snapshots_rels_ddl_dml():
    """Generate DDL and DML for volume snapshot relations"""
    # volume snapshot -[:created_from]-> volume
    cinder_snapshot_created_from_volume_query_lines = [
        "CREATE EDGE IF NOT EXISTS created_from();\n"
    ]

    for snapshot in get_all_volume_snapshots():
        # this is for demo purposes only, we even assume name is unique
        vertex_id = snapshot.name if snapshot.name else snapshot.id
        uuid_to_vertex_id[snapshot.id] = vertex_id
        if snapshot.volume_id:
            src = vertex_id
            dst = uuid_to_vertex_id[snapshot.volume_id]
            cinder_snapshot_created_from_volume_query_lines.append(
                f"INSERT EDGE created_from() VALUES "
                f"{_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )
    write_file(
        "edges/cinder.snapshot.created_from.ngql",
        cinder_snapshot_created_from_volume_query_lines,
    )


def generate_images_ddl_dml():
    """Generate DDL and DML for images"""
    image_query_lines = [
        "CREATE TAG image "
        "(id string, name string, status string, size int, min_disk int, "
        "min_ram int, created_at string, updated_at string);\n"
    ]
    glance_created_from_query_lines = ["CREATE EDGE IF NOT EXISTS created_from();\n"]
    cinder_volume_created_from_query_lines = [
        "CREATE EDGE IF NOT EXISTS created_from();\n"
    ]

    for image in get_all_images():
        # this is for demo purposes only, we even assume name is unique
        vertex_id = image.name if image.name else image.id
        uuid_to_vertex_id[image.id] = vertex_id
        DML_line = (
            f"INSERT VERTEX image (id, name, status, size, min_disk, "
            f"min_ram, created_at, updated_at) VALUES {_q}{vertex_id}{_q}:"
            f"({_q}{image.id}{_q}, {_q}{image.name}{_q}, {_q}{image.status}{_q}, "
            f"{image.size}, {image.min_disk}, {image.min_ram}, "
            f"{_q}{image.created_at}{_q}, "
            f"{_q}{image.updated_at}{_q});\n"
        )
        image_query_lines.append(DML_line)

        # image -[:created_from]-> volume snapshot
        # removed: this info is not persisted in OpenStack DB
        # if image.metadata.get("volume_id"):
        #     src = vertex_id
        #     dst = uuid_to_vertex_id[image.metadata.get("volume_id")]
        #     glance_created_from_query_lines.append(
        #         f"INSERT EDGE created_from() VALUES "
        #         f"{_q}{vertex_id}{_q} -> {_q}{dst}{_q}:();\n"
        #     )

    # let's mock we captured this info during its creation
    glance_created_from_query_lines.append(
        "INSERT EDGE created_from() VALUES "
        '"cirros_mod_from_volume-1" -> "volume-1":();\n'
    )
    for volume in get_all_volumes():
        # this is for demo purposes only, we even assume name is unique
        if volume.source_volid:
            src = volume.name if volume.name else volume.id
            dst = uuid_to_vertex_id[volume.source_volid]
            cinder_volume_created_from_query_lines.append(
                f"INSERT EDGE created_from() VALUES "
                f"{_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )
        if hasattr(
            volume, "volume_image_metadata"
        ) and volume.volume_image_metadata.get("image_id"):
            src = volume.name if volume.name else volume.id
            dst = uuid_to_vertex_id[volume.volume_image_metadata.get("image_id")]
            cinder_volume_created_from_query_lines.append(
                f"INSERT EDGE created_from() VALUES "
                f"{_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )

    write_file("vertices/glance.image.ngql", image_query_lines)
    write_file("edges/glance.image.created_from.ngql", glance_created_from_query_lines)
    write_file(
        "edges/cinder.volume.created_from.ngql", cinder_volume_created_from_query_lines
    )


def generate_keypairs_ddl_dml():
    """Generate DDL and DML for keypairs"""
    keypair_query_lines = [
        "CREATE TAG keypair (id string, name string, fingerprint string);\n"
    ]

    for key in get_all_keypairs():
        # this is for demo purposes only, we even assume name is unique
        vertex_id = key.name if key.name else key.id
        uuid_to_vertex_id[key.id] = vertex_id
        DML_line = (
            f"INSERT VERTEX keypair (id, name, fingerprint) "
            f"VALUES {_q}{vertex_id}{_q}:({_q}{key.id}{_q}, {_q}{key.name}{_q}, "
            f"{_q}{key.fingerprint}{_q});\n"
        )
        keypair_query_lines.append(DML_line)

    write_file("vertices/nova.keypair.ngql", keypair_query_lines)


def generate_instances_ddl_dml():
    glance_used_by_query_lines = ["CREATE EDGE IF NOT EXISTS used_by();\n"]
    nova_keypair_used_by_query_lines = ["CREATE EDGE IF NOT EXISTS used_by();\n"]

    # image -[:used_by]-> instance
    # keypair -[:used_by]-> instance
    for instance in get_all_instances():
        # this is for demo purposes only, we even assume name is unique
        dst = instance.name if instance.name else instance.id
        uuid_to_vertex_id[instance.id] = dst

        if instance.image:
            src = uuid_to_vertex_id[instance.image.get("id")]
            glance_used_by_query_lines.append(
                f"INSERT EDGE used_by() VALUES {_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )
        if instance.key_name:
            # there must be a name for keypair
            src = instance.key_name
            nova_keypair_used_by_query_lines.append(
                f"INSERT EDGE used_by() VALUES {_q}{src}{_q} -> {_q}{dst}{_q}:();\n"
            )

    write_file("edges/glance.image.used_by.ngql", glance_used_by_query_lines)
    write_file("edges/nova.keypair.used_by.ngql", nova_keypair_used_by_query_lines)


def main():
    # Order
    # - cinder_volume_created_from
    # - cinder_snapshot_created_from(dependent on cinder_volume_created_from)
    # - glance_created_from(dependent on cinder_volume_created_from)
    # - glance_used_by(dependent on glance_created_from)
    # - nova_keypair_used_by(dependent on nova_keypairs & nova_instances)
    generate_volumes_rels_ddl_dml()
    generate_volume_snapshots_rels_ddl_dml()
    generate_images_ddl_dml()
    generate_instances_ddl_dml()
    generate_keypairs_ddl_dml()


if __name__ == "__main__":
    main()
