from superset.app import create_app

app = create_app()
with app.app_context():
    from superset.extensions import security_manager
    gamma = security_manager.find_role("Gamma")
    db_pvm = security_manager.find_permission_view_menu("database_access", "[vdt_db].(id:1)")
    if db_pvm and db_pvm not in gamma.permissions:
        security_manager.add_permission_role(gamma, db_pvm)
        print("Granted database access to Gamma")
        app.appbuilder.get_session.commit()
