from superset.app import create_app

app = create_app()
with app.app_context():
    from superset.extensions import security_manager
    pvms = security_manager.get_session.query(security_manager.permissionview_model).all()
    for pvm in pvms:
        if pvm.permission.name == 'datasource_access':
            print(pvm.view_menu.name)
