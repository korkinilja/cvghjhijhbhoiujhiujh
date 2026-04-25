from django.db import migrations


def create_accounts_for_existing_owners(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    BudgetAccount = apps.get_model('maintabs', 'BudgetAccount')

    owners = User.objects.filter(account_type='owner', account__isnull=True)
    for owner in owners:
        account = BudgetAccount.objects.create(owner=owner, description='')
        owner.account = account
        owner.save(update_fields=['account'])


class Migration(migrations.Migration):

    dependencies = [
        ('maintabs', '0001_initial'),
        ('accounts', '0002_user_account')
    ]

    operations = [
        migrations.RunPython(
            create_accounts_for_existing_owners,
            migrations.RunPython.noop,
        ),
    ]