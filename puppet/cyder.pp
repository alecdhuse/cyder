class cyder {

  package { "apache2":
    ensure => present,
    ensure => "running",
  }
  
  service { "mysql":
    ensure => "running",
    enable => "true",
    require => Package["mysql-server"],
  }
  
}
