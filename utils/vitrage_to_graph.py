#!/usr/bin/env python3
import csv
import json
import os
import subprocess

from collections import defaultdict
from keystoneauth1.identity import v3
from keystoneauth1 import session
from vitrageclient.v1 import client as vitrage_client


def create_tag_schema_ddl(vitrage_type, keys):
    tag_name = vitrage_type.replace(".", "_")
    props = []
    for key in keys:
        if key != "vid":
            props.append(f"`{key}` string NULL")
    return f"CREATE TAG `{tag_name}`({', '.join(props)})"


def create_edge_type_schema_ddl(edge_type, keys):
    edge_type_name = edge_type.replace(".", "_")
    props = []
    for key in keys:
        if key not in ["src", "dst"]:
            props.append(f"`{key}` string NULL")
    return f"CREATE EDGE `{edge_type_name}`({', '.join(props)})"


def get_nebula_graph(vitrage_topology):
    if isinstance(vitrage_topology, str):
        data = json.loads(vitrage_topology)
    else:
        data = vitrage_topology
    # handle nodes
    nodes_by_type = defaultdict(list)
    edges_by_type = defaultdict(list)
    graph_index_to_vid = {}

    for node in data["nodes"]:
        vertex_id = (
            node["name"] if ("name" in node and node.get("name")) else node["id"]
        )
        uuid = node["id"]
        vitrage_type = node["vitrage_type"]
        state = node["state"]
        graph_index = node["graph_index"]

        node_info = {
            "vid": vertex_id,
            "name": vertex_id,
            "state": state,
            "uuid": uuid,
            "graph_index": graph_index,
        }
        graph_index_to_vid[graph_index] = vertex_id

        if vitrage_type == "neutron.port":
            node_info["ip_addresses"] = str(node["ip_addresses"])
        elif vitrage_type == "nova.instance":
            node_info["instance_name"] = node["instance_name"]
        elif vitrage_type == "cinder.volume":
            node_info["volume_type"] = node["volume_type"]
            node_info["attachments"] = str(node["attachments"])

        nodes_by_type[vitrage_type].append(node_info)

    # create the directory if it does not exist
    if not os.path.exists("vertices"):
        os.makedirs("vertices")

    for vitrage_type, nodes in nodes_by_type.items():
        filename = f"vertices/{vitrage_type}.csv"
        fieldnames = nodes[0].keys()
        with open(filename, mode="w") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for node in nodes:
                writer.writerow(node)

        filename = f"vertices/{vitrage_type}.ngql"
        props = [prop for prop in fieldnames if prop != "vid"]
        tag_name = vitrage_type.replace(".", "_")

        with open(filename, mode="w") as ngql_file:
            for node in nodes:
                vid = node["vid"]
                _q = '"'
                ngql_file.write(
                    f'INSERT VERTEX `{tag_name}`({",".join(props)}) '
                    f'VALUES "{vid}":'
                    f'({",".join([_q + str(node[prop]) + _q for prop in props])})'
                    f";\n"
                )

    for edge in data["links"]:
        edge_type = edge["relationship_type"]
        edge_info = {
            "src": edge["source"],
            "dst": edge["target"],
            "edge_type": edge_type,
        }
        edges_by_type[edge_type].append(edge_info)

    # create the directory if it does not exist
    if not os.path.exists("edges"):
        os.makedirs("edges")

    for edge_type, edges in edges_by_type.items():
        filename = f"edges/{edge_type}.csv"
        fieldnames = edges[0].keys()

        with open(filename, mode="w") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for edge in edges:
                edge["src"] = graph_index_to_vid[edge["src"]]
                edge["dst"] = graph_index_to_vid[edge["dst"]]
                writer.writerow(edge)

        filename = f"edges/{edge_type}.ngql"
        props = [prop for prop in fieldnames if prop not in ["src", "dst"]]

        with open(filename, mode="w") as ngql_file:
            for edge in edges:
                _q = '"'
                src = edge["src"]
                dst = edge["dst"]
                ngql_file.write(
                    f"INSERT EDGE `{edge_type}`({','.join(props)}) "
                    f"VALUES {_q}{src}{_q}->{_q}{dst}{_q}:"
                    f"({','.join([_q + str(edge[prop]) + _q for prop in props])})"
                    f";\n"
                )

    with open("schema.ngql", "w") as f:
        space_name = "openstack"
        create_space = (
            f"CREATE SPACE IF NOT EXISTS "
            f"{space_name} (partition_num=3, "
            f"replica_factor=1, "
            f"vid_type=fixed_string(128));"
        )
        use_space = f"USE {space_name};"

        f.write(create_space + "\n")
        f.write(use_space + "\n")
        for vitrage_type, nodes in nodes_by_type.items():
            keys = list(nodes[0].keys())
            f.write(create_tag_schema_ddl(vitrage_type, keys) + "\n")

        for edge_type, edges in edges_by_type.items():
            keys = list(edges[0].keys())
            f.write(create_edge_type_schema_ddl(edge_type, keys) + "\n")


def get_vitrage_topology():
    """Get topology of all tenants
    like CLI call of `vitrage topology show --all-tenants`
    """

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

    vitrage = vitrage_client.Client(session=sess)

    all_tenant_topology = vitrage.topology.get(all_tenants=True)
    return all_tenant_topology


def main():
    vitrage_topology = get_vitrage_topology()
    get_nebula_graph(vitrage_topology)


if __name__ == "__main__":
    main()
