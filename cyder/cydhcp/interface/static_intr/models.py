from gettext import gettext as _

from django.db import models
from django.core.exceptions import ValidationError

import cydns

from cyder.core.system.models import System

from cyder.base.constants import IP_TYPE_6

from cyder.cydhcp.keyvalue.base_option import CommonOption
from cyder.cydhcp.keyvalue.utils import AuxAttr
from cyder.cydhcp.utils import format_mac
from cyder.cydhcp.validation import validate_mac
from cyder.cydhcp.vrf.models import Vrf
from cyder.cydhcp.workgroup.models import Workgroup
from cyder.cydns.ptr.models import BasePTR, PTR

from cyder.cydns.address_record.models import AddressRecord, BaseAddressRecord
from cyder.cydns.ip.utils import ip_to_dns_form
from cyder.cydns.domain.models import Domain


class StaticInterface(BaseAddressRecord, BasePTR):
    # Keep in mind that BaseAddressRecord will have it's methods called before
    # BasePTR
    """The StaticInterface Class.

        >>> s = StaticInterface(label=label, domain=domain, ip_str=ip_str,
        ... ip_type=ip_type, dhcp_enabled=True, dns_enabled=True)
        >>> s.full_clean()
        >>> s.save()

    This class is the main interface to DNS and DHCP. A static
    interface consists of three key pieces of information: Ip address, Mac
    Address, and Hostname (the hostname is comprised of a label and a domain).
    From these three peices of information, three things are ensured: An A or
    AAAA DNS record, a PTR record, and a `host` statement in the DHCP builds
    that grants the mac address of the interface the correct IP address and
    hostname.

    If you want an A/AAAA, PTR, and a DHCP lease, create on of these objects.

    In terms of DNS, a static interface represents a PTR and A record and must
    adhear to the requirements of those classes. The interface inherits from
    BaseAddressRecord and will call it's clean method with
    'update_reverse_domain' set to True. This will ensure that it's A record is
    valid *and* that it's PTR record is valid.

    Using the 'attrs' attribute.

    To interface with the Key Value store of an interface use the 'attrs'
    attribute. This attribute is a direct proxy to the Keys and Values in the
    Key Value store. When you assign an attribute of the 'attrs' attribute a
    value, a key is create/updated. For example:

    >>> intr = <Assume this is an existing StaticInterface instance>
    >>> intr.update_attrs()  # This updates the object with keys/values already
    >>> # in the KeyValue store.
    >>> intr.attrs.primary
    '0'

    In the previous line, there was a key called 'primary' and it's value
    would be returned when you accessed the attribute 'primary'.

    >>> intr.attrs.alias
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
    AttributeError: 'attrs' object has no attribute 'alias'

    Here 'attrs' didn't have an attribute 'alias' which means that there was no
    KeyValue with key 'alias'. If we wanted to create that key and give it a
    value of '0' we would do:

    >>> intr.attrs.alias = '0'

    This *immediately* creates a KeyValue pair with key='alias' and value='0'.

    >>> intr.attrs.alias = '1'

    This *immediately* updates the KeyValue object with a value of '1'. It is
    not like the Django ORM where you must call the `save()` function for any
    changes to propagate to the database.
    """
    id = models.AutoField(primary_key=True)
    mac = models.CharField(max_length=17, validators=[validate_mac],
                           help_text='Mac address in format XX:XX:XX:XX:XX:XX')
    reverse_domain = models.ForeignKey(Domain, null=True, blank=True,
                                       related_name='reverse_staticintr_set')
    system = models.ForeignKey(
        System, null=True, blank=True,
        help_text='System to associate the interface with')

    vrf = models.ForeignKey(Vrf, null=True, blank=True)
    workgroup = models.ForeignKey(Workgroup, null=True, blank=True)

    dhcp_enabled = models.BooleanField(
        default=True, help_text='Enable dhcp for this interface?')
    dns_enabled = models.BooleanField(
        default=True, help_text='Enable dns for this interface?')

    attrs = None
    search_fields = ('mac', 'ip_str', 'fqdn')

    class Meta:
        db_table = 'static_interface'
        unique_together = ('ip_upper', 'ip_lower', 'label', 'domain', 'mac')

    def __repr__(self):
        return '<StaticInterface: {0}>'.format(str(self))

    def __str__(self):
        #return 'IP:{0} Full Name:{1} Mac:{2}'.format(self.ip_str,
        #        self.fqdn, self.mac)
        return self.fqdn

    def update_attrs(self):
        self.attrs = AuxAttr(StaticIntrKeyValue, self, 'intr')

    def details(self):
        data = super(StaticInterface, self).details()
        data['data'] = (
            ('Name', 'fqdn', self),
            ('IP', 'ip_str', str(self.ip_str)),
            ('MAC', 'mac', self.mac),
            ('Vrf', 'vrf', self.vrf),
            ('Workgroup', 'workgroup', self.workgroup),
            ('DHCP Enabled', 'dhcp_enabled',
                'True' if self.dhcp_enabled else 'False'),
            ('DNS Enabled', 'dns_enabled',
                'True' if self.dns_enabled else 'False'),
            ('DNS Type', '', 'A/PTR'),
        )
        return data

    @classmethod
    def get_api_fields(cls):
        return super(StaticInterface, cls).get_api_fields() + \
            ['mac', 'dhcp_enabled', 'dns_enabled']

    @property
    def rdtype(self):
        return 'INTR'

    def save(self, *args, **kwargs):
        urd = kwargs.pop('update_reverse_domain', True)
        self.clean_reverse(update_reverse_domain=urd)  # BasePTR
        super(StaticInterface, self).save(*args, **kwargs)
        self.rebuild_reverse()

    def delete(self, *args, **kwargs):
        if self.reverse_domain and self.reverse_domain.soa:
            self.reverse_domain.soa.schedule_rebuild()
            # The reverse_domain field is in the Ip class.
        super(StaticInterface, self).delete(*args, **kwargs)
        # ^ goes to BaseAddressRecord

    def check_A_PTR_collision(self):
        if PTR.objects.filter(ip_str=self.ip_str, name=self.fqdn).exists():
            raise ValidationError("A PTR already uses this Name and IP")
        if AddressRecord.objects.filter(ip_str=self.ip_str, fqdn=self.fqdn
                                        ).exists():
            raise ValidationError("An A record already uses this Name and IP")

    def interface_name(self):
        self.update_attrs()
        try:
            itype, primary, alias = '', '', ''
            itype = self.attrs.interface_type
            primary = self.attrs.primary
            alias = self.attrs.alias
        except AttributeError:
            pass
        if itype == '' or primary == '':
            return 'None'
        elif alias == '':
            return '{0}{1}'.format(itype, primary)
        else:
            return '{0}{1}.{2}'.format(itype, primary, alias)

    def build_host(self):
        build_str = '\thost {0} {{\n'.format(self.fqdn)
        build_str += '\t\thardware ethernet {0};\n'.format(
            format_mac(self.mac))
        if self.ip_type == IP_TYPE_6:
            build_str += '\t\tfixed-address6 {0};\n'.format(self.ip_str)
        else:
            build_str += '\t\tfixed-address {0};\n'.format(self.ip_str)
        """
        options = self.staticintrkeyvalue_set.filter(is_option=True)
        statements = self.staticintrkeyvalue_set.filter(is_statement=True)
        if options:
            build_str += '\t\t# Host Options\n'
            build_str += join_dhcp_args(options, depth=2)
        if statements:
            build_str += '\t\t# Host Statements\n'
            build_str += join_dhcp_args(statements, depth=2)
        """
        build_str += '\t}\n\n'
        return build_str

    def build_subclass(self, contained_range, allowed):
        return "subclass \"{0}:{1}:{2}\" 1:{3};\n".format(
            allowed.name, contained_range.start_str, contained_range.end_str,
            format_mac(self.mac))

    def clean(self, *args, **kwargs):
        self.mac = self.mac.lower()
        if not self.system:
            raise ValidationError(
                "An interface means nothing without it's system."
            )

        from cyder.cydns.ptr.models import PTR
        if PTR.objects.filter(ip_str=self.ip_str, name=self.fqdn).exists():
            raise ValidationError('A PTR already uses this Name and IP')
        if AddressRecord.objects.filter(ip_str=self.ip_str, fqdn=self.fqdn
                                        ).exists():
            raise ValidationError('An A record already uses this Name and IP')

        if kwargs.pop('validate_glue', True):
            self.check_glue_status()

        super(StaticInterface, self).clean(validate_glue=False,
                                           ignore_intr=True)

    def check_glue_status(self):
        """If this interface is a 'glue' record for a Nameserver instance,
        do not allow modifications to this record. The Nameserver will
        need to point to a different record before this record can
        be updated.
        """
        if self.pk is None:
            return
        # First get this object from the database and compare it to the
        # Nameserver object about to be saved.
        db_self = StaticInterface.objects.get(pk=self.pk)
        if db_self.label == self.label and db_self.domain == self.domain:
            return
        # The label of the domain changed. Make sure it's not a glue record
        Nameserver = cydns.nameserver.models.Nameserver
        if Nameserver.objects.filter(intr_glue=self).exists():
            raise ValidationError(
                "This Interface represents a glue record for a "
                "Nameserver. Change the Nameserver to edit this record.")

    a_template = _("{bind_name:$rhs_just} {ttl} {rdclass:$rdclass_just}"
                   "{rdtype_clob:$rdtype_just} {ip_str:$lhs_just}")
    ptr_template = _("{dns_ip:$lhs_just} {ttl} {rdclass:$rdclass_just}"
                     " {rdtype_clob:$rdtype_just} {fqdn:1}.")

    def bind_render_record(self, pk=False, **kwargs):
        self.rdtype_clob = kwargs.pop('rdtype', 'INTR')
        if kwargs.pop('reverse', False):
            self.template = self.ptr_template
            self.dns_ip = ip_to_dns_form(self.ip_str)
        else:
            self.template = self.a_template
        return super(StaticInterface, self).bind_render_record(pk=pk, **kwargs)

    def obj_type(self):
        return 'A/PTR'


class StaticIntrKeyValue(CommonOption):
    intr = models.ForeignKey(StaticInterface, null=False)

    class Meta:
        db_table = 'static_interface_kv'
        unique_together = ('key', 'value', 'intr')
