from utilities import get_cursor, ip2long, long2ip, clean_mac, config
from ConfigParser import ConfigParser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
import chili_manage, fix_maintain, maintain_dump
from cyder.core.ctnr.models import Ctnr
from cyder.cydhcp.vlan.models import Vlan
from cyder.cydhcp.site.models import Site
from cyder.cydhcp.network.models import Network
from cyder.cydhcp.range.models import Range
from cyder.cydhcp.workgroup.models import Workgroup
import ipaddr

def calc_prefixlen(netmask):
    bits = 0
    while netmask:
        bits += netmask & 1
        netmask >>= 1
    return bits

cursor = get_cursor('maintain_sb')

def create_subnet(id, name, subnet, netmask, status, vlan):
    """
    Takes a row from the Maintain subnet table
    returns a new network object and creates the vlan it is associated with
    """
    s, _ = Site.objects.get_or_create(name='Campus')
    v = None
    try:
        cursor.execute("SELECT * FROM vlan WHERE vlan_id = %s"%vlan)
        id, vlan_name, vlan_id = cursor.fetchone()
        v = Vlan.objects.get(name=vlan_name, number=vlan_id)
    except:
        print "vlan does not exist {0}".format(vlan)
    network = long2ip(subnet)
    prefixlen = str(calc_prefixlen(netmask))
    n = Network.objects.get_or_create(
            network_str = network + '/' + prefixlen, ip_type='4',
            site=s, vlan=v)
    return n

def create_range(id, start, end, type, subnet_id, comment, enabled, parent, allow_all_hosts):
    """
    Takes a row form the Maintain range table
    returns a range which is saved in cyder
    """
    try:
        cursor.execute("SELECT * FROM subnet WHERE id = {0}".format(subnet_id))
        id, name, subnet, netmask, status, vlan = cursor.fetchone()
    except:
        print ("Unable to find subnet with id {0}\n"
              "associated with range from {1} to {2}".format(subnet_id, start, end))
        return
    r_type = 'st' if type == 'static' else 'dy'
    n = Network.objects.get(ip_lower=subnet, prefixlen=str(calc_prefixlen(netmask)))
    r = Range(start_lower=start, start_str=ipaddr.IPv4Address(start),
    end_lower=end, end_str=ipaddr.IPv4Address(end), network=n,
    range_type=r_type)
    try:
        r.save()
        return r
    except:
        print "cant create range {0} to {1} in {2}".format(start, end, n.network_str)

def create_zone(id, name, description, comment, purgeable, support_mail, notify, allow_blank):
    """
    Takes a row from the Maintain zone table
    returns a newly made container and creates the many to many relatiosnhip
    between the new ctnr and it's associated range
    """
    c = Ctnr.objects.get_or_create(name=name, description=comment or description)
    c.save()
    """
    We need to also create the workgroups and related them to containers
    """
    try:
        cursor.execute("SELECT zone_range.range "
                       "FROM zone_range "
                       "WHERE zone = {0}".format(id))
        for row in cursor.fetchall():
            cursor.execute("SELECT * FROM `ranges` WHERE id={0}".format(row[0]))
            _, start, end, _, _, _, _, _, _ = cursor.fetchone()
            r = Range.objects.get(start_lower=start, end_lower=end)
            c.ranges.add(r)
    except:
        print ("Unable to find any ranges associated with "
                        "{0} {1}".format(id, name))
        return

def migrate_subnets():
    created = []
    cursor.execute("SELECT * FROM subnet")
    result = cursor.fetchall()
    for row in result:
        created.append(create_subnet(*row))

def migrate_ranges():
    created = []
    cursor.execute("SELECT * FROM ranges")
    result = cursor.fetchall()
    for row in result:
        created.append(create_range(*row))

def migrate_vlans():
    cursor.execute("SELECT * FROM vlan")
    for row in cursor.fetchall():
        _, name, number = row
        Vlan.objects.get_or_create(name=name, number=number)

def migrate_workgroups():
    cursor.execute("SELECT * FROM workgroup")
    for row in cursor.fetchall():
        id, name = row
        vrf, _ = Workgroup.objects.get_or_create(name=name)

def create_ctnr(id):
    cursor.execute("SELECT * FROM zone WHERE id={0}".format(id))
    _, name, desc, comment, _, _, _, _ = cursor.fetchone()
    c, _ = Ctnr.objects.get_or_create(name=name, description=comment or desc)
    return c

def migrate_zones():
    cursor.execute("SELECT * FROM zone")
    result = cursor.fetchall()
    for _, name, desc, comment, _, _, _, _ in result:
        c, _ = Ctnr.objects.get_or_create(name=name, description=comment or desc)

def migrate_zone_range():
    cursor.execute("SELECT * FROM zone_range WHERE enabled = 1")
    result = cursor.fetchall()
    for _, zone_id, range_id, _, comment, _ in result:
        cursor.execute("SELECT name FROM zone WHERE id = {0}".format(zone_id))
        try:
            zone_name = cursor.fetchone()
            if not zone_name:
                continue
        except:
            print "zone with id {0} does not exist".format(zone_id[0])
            continue
        try:
            cursor.execute("SELECT start, end "
                           "FROM `ranges` "
                           "WHERE id = {0}".format(range_id))
            r_start, r_end = cursor.fetchone()
        except:
            print "range with id {0} does not exist".format(range_id)
            continue
        try:
            c = Ctnr.objects.get(name=zone_name[0])
        except:
            print "can't find container named {0}".format(zone_name[0])
            continue
        try:
            r = Range.objects.get(start_lower=r_start, end_lower=r_end)
        except:
            print ("can't find range with "
                   "start_lower = {0} and end_lower = {1}". format(r_start, r_end))
            continue
        c.ranges.add(r)

def migrate_zone_workgroup():
    cursor.execute("SELECT * FROM zone_workgroup")
    result = cursor.fetchall()
    for _, workgroup_id, zone_id, _ in result:
        try:
            cursor.execute("SELECT name FROM zone WHERE id={0}".format(zone_id))
            zone_name = cursor.fetchone()
            if not zone_name:
                continue
        except:
            print "zone with id {0} does not exist".format(zone_id)
            continue
        try:
            cursor.execute("SELECT * FROM workgroup WHERE id={0}".format(zone_id))
            _, w_name = cursor.fetchone()
        except:
            print "workgroup with id {0} does not exist".format(zone_id)
            continue
        try:
            c = Ctnr.objects.get(name=zone_name[0])
        except:
            print "can't find container named {0}".format(zone_name[0])
            continue
        try:
            w = Workgroup.objects.get(name=w_name)
        except:
            print "can't find workgroup named {0}".format(w_name)
            continue
        c.workgroups.add(w)

def find_zone(zone_id):
    cursor.execute("SELECT name FROM zone WHERE id = {0}".format(zone_id))
    c = None
    try:
        name = cursor.fetchone()[0]
        c = Ctnr.objects.get(name=name)
    except e:
        print e
    return c

def find_domain(domain_id):
    cursor.execute("SELECT name from domain WHERE id = {0}".format(domain_id))
    d = None
    try:
        name = cursor.fetchone()[0]
        d = Domain.objects.get(name=name)
    except e:
        print e
    return d

def find_range(range_id):
    cursor.execute("SELECT start, end FROM ranges WHERE id = {0}".format(range_id))
    r = None
    try:
        start, end = cursor.fetchone()
        r = Range.objects.get(start_str=ipaddr.IPv4Address(start),
                end_str=ipaddr.IPv4Address(end))
    except e:
        print e
    r = Range(start_lower=start, start_str=ipaddr.IPv4Address(start),
                end_lower=end, end_str=ipaddr.IPv4Address(end), network=n,
                range_type=r_type)


def migrate_hosts():
    cursor.execute(
            "SELECT ip, dynamic_range, name, domain, ha, "
            "location, zone, department "
            "FROM host "
            "WHERE enabled = 1")
    results = cursor.fetchall()
    for row in results:
        ip, d_range, name, domain, mac, location, zone, department = row
        s, _ = System.objects.get_or_create(
                name=name, location=location, department=department)
        d = find_domain(domain)
        c = find_zone(zone)
        if d_range:
            r = find_range(d_range)
            intr, _ = DynamicInterface.objects.get_or_crate(range=r, ctnr=c,
                    mac=mac, system=s)
        else:
            intr, _ = StaticInterface.objects.get_or_create(
                    ip_str=ipaddr.IPv4Address(ip), mac=mac,
                    system=s, domain=d, dhcp_enabled=1, dns_enabled=1)


def migate_users():
    cursor.execute("SELECT id, username, type, preferred_zone, email "
                   "FROM users")
    results = cursor.fetchall():
    for row in results:
        user_id, username, auth_type, zone_id, email = row
        # Create and save user
        cursor.execute("SELECT zone, level "
                       "FROM zone_user "
                       "WHERE username = \"{0}\"".format(username))
        user_privs = cursor.fetchall()
        for zone_id, level in user_privs:
            try:
                cursor.execute("SELECT name "
                               "FROM zone "
                               "WHERE id = {0}".format(zone_id))
                try:
                    zone_name = cursor.fetchone()[0]
                    c = Ctnr.objects.get(name=zone_name)


migrate_users()
migrate_vlans()
migrate_workgroups()
migrate_subnets()
migrate_ranges()
migrate_zones()
migrate_zone_range()
migrate_zone_workgroup()
migrate_hosts()